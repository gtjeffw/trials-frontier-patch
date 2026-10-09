"""List every level with its environment pool, from the unpacked content packs.

Usage: python3 -I level_info.py <unpacked_dir> <TrialsFrontier executable> [--csv out.csv] [--env name]

Level files (/level/<F from levels.txt>) are mt::file::SaveFile data written with the default Protection
(constant at 0x100aed960: seed 0x97, mult 0x1F49) and a 16-byte header; the body is a chunk stream
(u32 tags, little-endian: 'TRGO' file magic, then 'HEAD', 'META', 'VISU', 'PHYS', ...). tr::LevelLoader::loadLevel
reads 0x20 bytes after 'HEAD' into a LevelHeader; tr::GameWorld::loadResources uses byte 4 as the object/environment
pool (index into the pool list, content file /conf pool definitions 0xd2aeca5a) and byte 6 as a variant.
"""
import csv
import json
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decode_save import unscramble  # noqa: E402


def game_hash(s):
    b = s.encode()
    n, x = len(b), 0
    for c in b:
        c = c - 256 if c > 127 else c
        x = (x + n * c) & 0xFFFFFFFF
        n = ((n & 0xFFFF) * 18000 + (n >> 16)) & 0xFFFFFFFF
    return x


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


csv_out, env_filter = opt("--csv"), opt("--env")
unpacked, exe_path = sys.argv[1:3]
exe = open(exe_path, "rb").read()
seed, mult = struct.unpack_from("<2I", exe, 0xAED960)

files = {}
for d in os.listdir(unpacked):
    if d == "tex":
        continue
    for f in os.listdir(os.path.join(unpacked, d)):
        files[int(f[:8], 16)] = (d, os.path.join(unpacked, d, f))
blob = lambda name: files[game_hash(name)][1]
levels = json.load(open(blob("/conf/levels.txt")))["Levels"]
pools = [l.strip() for l in open(blob("/conf/objcombiner_pools"), encoding="ascii", errors="replace") if l.strip()] \
    if game_hash("/conf/objcombiner_pools") in files else \
    [l.strip() for l in open(os.path.join(unpacked, "content", "d2aeca5a.bin"), encoding="ascii", errors="replace") if l.strip()]

strings = {}
d = open(blob("/gen/lang/english_strings.bin"), "rb").read()
i = 9
while i + 6 <= len(d):
    k, ln = struct.unpack_from("<IH", d, i)
    strings[k] = d[i + 6:i + 6 + ln].rstrip(b"\0").decode("utf-8", "replace")
    i += 6 + ln

rows = []
for lv in levels:
    pack, path = files[game_hash("/level/" + lv["F"])]
    p = unscramble(open(path, "rb").read(), seed, mult)
    size = struct.unpack_from("<I", p, 8)[0]
    body = zlib.decompress(p[16:]) if size else p[16:]
    h = body.find(b"DAEH")
    head = body[h + 4:h + 4 + 0x20]
    pool = head[4]
    rows.append({"id": lv["ID"], "name": strings.get(game_hash(lv["N"]), lv["N"]), "key": lv["N"],
                 "env": pools[pool] if pool < len(pools) else f"pool{pool}", "pool": pool, "variant": head[6],
                 "pack": pack, "file": lv["F"]})
rows.sort(key=lambda r: (r["env"], r["id"]))
for r in rows:
    if env_filter and env_filter not in r["env"]:
        continue
    print(f"{r['id']:>5}  {r['env']:<11} {r['name']:<28} {r['pack']}")
if csv_out:
    with open(csv_out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
counts = {}
for r in rows:
    counts[r["env"]] = counts.get(r["env"], 0) + 1
print("levels per environment:", dict(sorted(counts.items())))
