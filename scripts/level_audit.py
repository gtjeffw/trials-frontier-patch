"""Which levels a player has raced, owns but has not raced, or cannot reach any more.

Usage: python3 -I level_audit.py <player.bin> <unpacked content dir> [--groups trialstrackmap/ids.json] [--csv out.csv]

Sources (TrialsFrontier 7.9.0):
- Levels: /conf/levels.txt (content a2263380): N name key, ID, X/Y map position. LevelMetaData::isAvailableOnMap is
  X^2 + Y^2 < 8000^2; the 6 levels outside sit at (-10000, -10000). Names: /gen/lang/english_strings.bin.
- Raced: the save's score table (see extract_scores.py).
- Owned: PlayerItems (decoded save offset 0x914; slot value = ror(stored ^ 0xab1d4f5, 7)):
  slots 850-999 = rewarded/bought levels, two u16 level ids per slot (PlayerItems::getRewardedLevels, items 170-199
  via addRewardedLevel); slots 1001-1099 = map-piece levels, u16 level id + u16 pieces (getCraftingLevels).
- Not counted: levels opened by solved missions, daily rewards or robot missions without a time, so "hidden" can
  include a few levels that are visible on the map.
--groups takes dutscher/trialstrackmap database/trackdata/ids.json (MIT; JSON with // comments) to label levels by
the site's tier/event comments.
"""
import csv
import glob
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datapack import game_hash  # noqa: E402
from decode_save import decode  # noqa: E402

ITEMS = 0x914
KEY = 0xAB1D4F5


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


def scores(raw):
    def is_record(off):
        f = struct.unpack_from("<16I", raw, off)
        return f[0] < 0x1000000 and (f[9] == 0 or f[9] + f[10] + f[8] * 3600000 == 360000000)
    best = None
    for start in range(0, len(raw) - 68, 4):
        n = struct.unpack_from("<I", raw, start)[0]
        if 1 <= n <= 2000 and start + 4 + n * 64 <= len(raw) and all(is_record(start + 4 + i * 64) for i in range(n)):
            timed = sum(1 for i in range(n) if struct.unpack_from("<I", raw, start + 4 + i * 64 + 36)[0])
            if best is None or timed > best[2]:
                best = (start, n, timed)
    return {struct.unpack_from("<I", raw, best[0] + 4 + i * 64)[0] & 0xFFFF for i in range(best[1])
            if struct.unpack_from("<I", raw, best[0] + 4 + i * 64 + 36)[0]} if best else set()


def item(raw, slot):
    u = struct.unpack_from("<I", raw, ITEMS + 4 * slot)[0] ^ KEY
    return ((u >> 7) | (u << 25)) & 0xFFFFFFFF


groups_path, csv_out = opt("--groups"), opt("--csv")
save_path, content = sys.argv[1:3]
_, raw = decode(open(save_path, "rb").read())
raced = scores(raw)
owned, pieces = set(), {}
for slot in range(850, 1000):
    v = item(raw, slot)
    owned |= {x for x in (v & 0xFFFF, v >> 16) if x}
for slot in range(1001, 1100):
    v = item(raw, slot)
    if v & 0xFFFF:
        pieces[v & 0xFFFF] = v >> 16

levels = json.load(open(os.path.join(content, "%08x.bin" % game_hash("/conf/levels.txt"))))["Levels"]
names_path = glob.glob(os.path.join(content, "..", "*", "%08x.bin" % game_hash("/gen/lang/english_strings.bin")))
data, strings, i = open(names_path[0], "rb").read(), {}, 9
while i + 6 <= len(data):
    k, ln = struct.unpack_from("<IH", data, i)
    strings[k] = data[i + 6:i + 6 + ln].rstrip(b"\0").decode("utf-8", "replace")
    i += 6 + ln
group = {}
if groups_path:
    cur, prev = "", None
    for line in open(groups_path):
        s = line.strip()
        if s.startswith("//"):
            cur, prev = (prev if prev is not None else cur), s[2:].strip()
        elif s.startswith("{"):
            prev = None
        m = re.search(r'"oid":\s*(\d+)', s)
        if m:
            group[int(m.group(1))] = cur

rows = []
for lv in levels:
    lid, key = lv["ID"], lv["N"]
    named = game_hash(key) in strings
    on_map = lv["X"] ** 2 + lv["Y"] ** 2 < 8000 ** 2
    state = ("raced" if lid in raced else "owned" if lid in owned or pieces.get(lid, 0) >= 10 else
             "pieces %d/10" % pieces[lid] if lid in pieces else "off map" if not on_map else
             "test level" if not named else "hidden")
    rows.append({"id": lid, "name": strings.get(game_hash(key), key), "state": state, "group": group.get(lid, ""),
                 "x": lv["X"], "y": lv["Y"], "file": lv["F"]})
counts = {}
for r in rows:
    counts[r["state"].split(" ")[0]] = counts.get(r["state"].split(" ")[0], 0) + 1
print("levels:", len(rows), dict(sorted(counts.items())))
for state in ("hidden", "pieces", "off"):
    sel = [r for r in rows if r["state"].startswith(state)]
    if sel:
        print(f"\n{state} ({len(sel)}):")
        for r in sorted(sel, key=lambda r: (r["group"], r["name"])):
            print(f"  {r['id']:5d}  {r['name']:26s} {r['state']:12s} {r['group']}")
if csv_out:
    with open(csv_out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
