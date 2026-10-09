"""List Trials Frontier ghost_*.bin replays with owner, track, finish time and file dates.

Usage: python3 -I list_ghosts.py <extracted_dir_containing_AppDomain-...> [--csv out.csv]

Ghost layout (as observed): 16-byte header (u32 version, u32 hash, u32 raw_len, u32 0), then zlib.
Decompressed payload starts with:
  version 2: u32 finish time ms, u32 sample count
  version 3: u32 bike id (probably), u32 finish time ms, u32 sample count
Samples are ~133 ms apart, which is how the time field was confirmed.
"""
import csv
import datetime
import os
import plistlib
import re
import sqlite3
import sys
import zlib

root = sys.argv[1]
csv_out = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None
app = os.path.join(root, "AppDomain-com.ubisoft.redlynx.trialsfrontier")
docs = os.path.join(app, "Documents")

# real on-device timestamps live in the manifest subset saved next to the extracted files
dates = {}
manifest = os.path.join(root, "Manifest-trialsfrontier.db")
if os.path.exists(manifest):
    db = sqlite3.connect(f"file:{os.path.abspath(manifest)}?immutable=1", uri=True)
    for rel, blob in db.execute("SELECT relativePath, file FROM Files WHERE flags = 1"):
        p = plistlib.loads(blob)
        top = p["$objects"][p["$top"]["root"].data]
        dates[rel] = (top.get("Birth"), top.get("LastModified"))


def fmt_date(ts):
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""


rows = []
for name in sorted(os.listdir(docs)):
    m = re.fullmatch(r"ghost_([0-9a-fA-F]+)_(\d+)\.bin", name)
    if not m:
        continue
    raw = open(os.path.join(docs, name), "rb").read()
    version = int.from_bytes(raw[0:4], "little")
    u32 = lambda d, i: int.from_bytes(d[i * 4:i * 4 + 4], "little")
    try:
        data = zlib.decompress(raw[16:])
        bike, ms, samples = (None, u32(data, 0), u32(data, 1)) if version == 2 else (u32(data, 0), u32(data, 1), u32(data, 2))
    except zlib.error:
        bike = ms = samples = None
    if ms and samples and not 120 < ms / samples < 145:
        print(f"warning: {name} time/sample ratio {ms / samples:.1f} ms looks wrong", file=sys.stderr)
    born, modified = dates.get(f"Documents/{name}", (None, None))
    rows.append({
        "file": name,
        "owner": m.group(1),
        "track": int(m.group(2)),
        "format": version,
        "bike": bike,
        "time": f"{ms // 60000}:{ms % 60000 / 1000:06.3f}" if ms is not None else "?",
        "time_ms": ms,
        "samples": samples,
        "created": fmt_date(born),
        "modified": fmt_date(modified),
    })

rows.sort(key=lambda r: (r["owner"] != "0", r["owner"], r["track"]))
for r in rows:
    print(f"{r['owner']:>8}  track {r['track']:>5}  {r['time']:>9}  bike {r['bike']!s:>4}  {r['created']} -> {r['modified']}")

owners = {}
for r in rows:
    owners[r["owner"]] = owners.get(r["owner"], 0) + 1
print(f"\n{len(rows)} ghosts; by owner: {owners}")

if csv_out:
    with open(csv_out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {csv_out}")
