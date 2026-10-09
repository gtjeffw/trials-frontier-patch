"""Join decoded best scores with track names, medal thresholds and ghost files into one CSV.

Usage: python3 -I build_report.py <unpacked_content_dir> <scores.csv> <ghosts.csv> <out.csv>

Inputs:
  unpacked_content_dir: content.dat unpacked by unpack_datapack.py (files named by name hash)
  scores.csv: from extract_scores.py      ghosts.csv: from list_ghosts.py
Names/hashes use mt::String::getHashCode (see game_hash below); levels come from /conf/levels.txt,
English names from /gen/lang/english_strings.bin (LOCF: u32 key hash, u16 length, text NUL).
Medal tiers (order confirmed by an in-game "silver" screenshot): time <= M0 and faults <= F0 -> platinum,
then M1/F1 gold, M2/F2 silver, M3/F3 bronze. "platinum" is the name we assume for the top tier.
"""
import csv
import json
import os
import struct
import sys


def game_hash(s):
    b = s.encode()
    n, x = len(b), 0
    for c in b:
        c = c - 256 if c > 127 else c
        x = (x + n * c) & 0xFFFFFFFF
        n = ((n & 0xFFFF) * 18000 + (n >> 16)) & 0xFFFFFFFF
    return x


def load_strings(path):
    d = open(path, "rb").read()
    table, i = {}, 9  # header: "LOCF", u8 version, u32
    while i + 6 <= len(d):
        key, length = struct.unpack_from("<IH", d, i)
        text = d[i + 6:i + 6 + length].rstrip(b"\0").decode("utf-8", "replace")
        table[key] = text
        i += 6 + length
    return table


content, scores_csv, ghosts_csv, out = sys.argv[1:5]
blob = lambda name: os.path.join(content, f"{game_hash(name):08x}.bin")
levels = {l["ID"]: l for l in json.load(open(blob("/conf/levels.txt")))["Levels"]}
strings = load_strings(blob("/gen/lang/english_strings.bin"))
ghosts = {int(r["track"]): r for r in csv.DictReader(open(ghosts_csv))}

MEDALS = ["platinum", "gold", "silver", "bronze"]
rows = []
for s in csv.DictReader(open(scores_csv)):
    track, variant = int(s["base_track"]), int(s["variant"])
    lvl = levels.get(track, {})
    ms = int(s["time_ms"]) if s["time_ms"] else None
    faults = int(s["faults"])
    medal = ""
    if ms is not None and lvl:
        for i, name in enumerate(MEDALS):
            if ms <= lvl[f"M{i}"] and faults <= lvl[f"F{i}"]:
                medal = name
                break
    g = ghosts.get(track) if variant == 0 else None
    rows.append({
        "track_id": track,
        "variant": variant,
        "name": strings.get(game_hash(lvl["N"]), lvl["N"]) if lvl else "",
        "key": lvl.get("N", ""),
        "difficulty": lvl.get("D", ""),
        "best_time": s["time"],
        "faults": faults if ms is not None else "",
        "medal": medal,
        "platinum_time": f"{lvl['M0'] / 1000:.3f}" if lvl else "",
        "bike": s["bike"],
        "ghost_file": g["file"] if g else "",
        "ghost_time": g["time"] if g else "",
    })
# ghosts with no score record (e.g. event tracks)
scored = {(r["track_id"], r["variant"]) for r in rows}
for t, g in ghosts.items():
    if (t, 0) not in scored:
        lvl = levels.get(t, {})
        rows.append({"track_id": t, "variant": 0, "name": strings.get(game_hash(lvl["N"]), lvl["N"]) if lvl else "",
                     "key": lvl.get("N", ""), "difficulty": lvl.get("D", ""), "best_time": "", "faults": "",
                     "medal": "", "platinum_time": "", "bike": g["bike"], "ghost_file": g["file"], "ghost_time": g["time"]})
rows.sort(key=lambda r: (r["track_id"], r["variant"]))
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)
print(f"wrote {out}: {len(rows)} rows")
