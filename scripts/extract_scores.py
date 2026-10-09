"""Extract per-track best scores from a decoded Trials Frontier save (see decode_save.py).

Usage: python3 -I extract_scores.py <player.raw> [--csv out.csv]

Layout (from tr::Player::loadScores): u32 count, then count x (u32 track_id, 60-byte tr::PlayerScores).
PlayerScores as u32 fields (meaning of some still unconfirmed):
  0: 0xff marker    1: ?    2: unknown_a (small int)    3-6: unknown_b..e (often 10)
  7: faults    8: best time ms    9: 360000000 - time - faults*3600000 (integrity copy; faults outrank time)
  10: bike id (matches ghost files)    11-13: ?    14: unknown_f
Track ids can carry flags in the high bits (e.g. 66573 = 0x10000 | 1037); base_track = id & 0xffff.
"""
import csv
import struct
import sys

raw = open(sys.argv[1], "rb").read()
csv_out = sys.argv[sys.argv.index("--csv") + 1] if "--csv" in sys.argv else None


def is_record(off):
    if off + 64 > len(raw):
        return False
    f = struct.unpack_from("<16I", raw, off)
    return f[1] & 0xFF == 0xFF and (f[9] == 0 or f[9] + f[10] + f[8] * 3600000 == 360000000)


# find the table: the longest run of 64-byte records preceded by a matching count
best = None
for start in range(0, len(raw) - 68, 4):
    n = struct.unpack_from("<I", raw, start)[0]
    if 1 <= n <= 2000 and start + 4 + n * 64 <= len(raw) and all(is_record(start + 4 + i * 64) for i in range(n)):
        if best is None or n > best[1]:
            best = (start, n)
if not best:
    sys.exit("score table not found")
start, n = best

rows = []
for i in range(n):
    f = struct.unpack_from("<16I", raw, start + 4 + i * 64)
    ms = f[9]
    rows.append({
        "track": f[0],
        "base_track": f[0] & 0xFFFF,
        "variant": f[0] >> 16,
        "faults": f[8],
        "time_ms": ms if ms else None,
        "time": f"{ms // 60000}:{ms % 60000 / 1000:06.3f}" if ms else "",
        "bike": f[11],
        "unknown_a": f[3],
        "unknown_bcde": f"{f[4]},{f[5]},{f[6]},{f[7]}",
        "unknown_f": f[15],
        "integrity_ok": ms == 0 or f[9] + f[10] + f[8] * 3600000 == 360000000,
    })
rows.sort(key=lambda r: r["track"])
print(f"score table at offset {start}: {n} tracks, {sum(1 for r in rows if r['time_ms'])} with a time")
for r in rows:
    print(f"track {r['base_track']:>5}/{r['variant']}  {r['time']:>9}  {r['faults']}F  bike {r['bike']:>3}  a={r['unknown_a']:<3} bcde={r['unknown_bcde']:<14} f={r['unknown_f']}")
if csv_out:
    with open(csv_out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {csv_out}")
