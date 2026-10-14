"""The game's friends leaderboard cache, Library/Caches/lbstorage.bin: read, write, export.

Usage: python3 -I lbcache.py show <lbstorage.bin>
       python3 -I lbcache.py export <lbstorage.bin> <out.json>

While the game was online it kept the friends tab of every leaderboard the player opened in this file (the global
lists were never written to disk). Each entry is a friend's public leaderboard entry: real profile id, name, rank,
time, faults, bike, upgrades. Backups skip Library/Caches, so a copy exists only where the original game's data is
still on disk: an Apple silicon Mac that ran the App Store version (~/Library/Containers/
com.ubisoft.redlynx.trialsfrontier/Data/Library/Caches/), a jailbroken device, ... The game empties the file when it
logs out or resets its login, and a patched game in the same container rewrites it with local-server data: copy it
before starting any game on that data.

Format (tr::OnlineDataContainer::saveFriendLeaderBoardCacheToDevice / loadFriendLeaderBoardCacheFromDevice; a
mt::file::SaveFile with the engine's default protection: no XOR stream, header version 6, checksum
SaveFile::fletcher32 keyed 0xec51a7/0x2141 over the uncompressed data, zlib):
  u32 boards; per board: u32 cached at (Unix time), u32 leaderboard id (track | class bits, 0 = Hall of Fame),
  u32 a, u32 b, u8 flag, u32 entries; per entry (tr::LeaderboardPlayerItem, 0x8c bytes in memory, 135 on disk):
  char[0x29] profile id, char[0x21] name, u32 rank, 0x30 bytes LeaderBoardData (u32 upgrades[4], faults,
  drive time ms, score_value, bike, ..., u32 at +0x2c: upgrades >> 6 & 0x3ff), u32 (low byte kept), i32, u8.
The export keeps what the game showed (names, times, faults, bikes) and replaces profile ids with the hashes bundles
use (game hash, profile sha256): a raw profile id is enough to claim someone's rider in the community layer.
"""
import json
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from decode_save import fletcher32  # noqa: E402
from ghost_bundle import profile_hashes  # noqa: E402

VERSION, CHECK_SEED, CHECK_MULT = 6, 0xEC51A7, 0x2141
EXPORT_FORMAT = "trials-frontier-leaderboard-cache"
ENTRY = struct.Struct("<41s33sI48sIiB")  # 135 bytes


class CacheError(ValueError):
    pass


def cstr(b):
    return b.split(b"\0")[0].decode("utf-8", "replace")


def read(data):
    """[{cached_at, leaderboard, a, b, flag, entries: [{profile, name, rank, upgrades, faults, time_ms, score_value,
    bike, raw}]}]; raw keeps every byte for write()."""
    if len(data) < 16:
        raise CacheError("too short")
    version, check, size, _ = struct.unpack_from("<4I", data)
    if version != VERSION:
        raise CacheError(f"version {version}, expected {VERSION}")
    try:
        body = zlib.decompress(data[16:])
    except zlib.error as e:
        raise CacheError(f"not compressed data ({e})") from None
    if len(body) != size or fletcher32(body, CHECK_SEED, CHECK_MULT) != check:
        raise CacheError("checksum or size mismatch")
    boards, off = [], 4
    try:
        for _ in range(struct.unpack_from("<I", body, 0)[0]):
            cached_at, lb, a, b, flag, n = struct.unpack_from("<4IBI", body, off)
            off += 21
            entries = []
            for _ in range(n):
                pid, name, rank, block, x, y, z = ENTRY.unpack_from(body, off)
                off += ENTRY.size
                up = struct.unpack_from("<12I", block)
                entries.append({"profile": cstr(pid), "name": cstr(name), "rank": rank, "upgrades": list(up[0:4]),
                                "faults": up[4], "time_ms": up[5], "score_value": up[6], "bike": up[7],
                                "raw": [pid.hex(), name.hex(), block.hex(), x, y, z]})
            boards.append({"cached_at": cached_at, "leaderboard": lb, "a": a, "b": b, "flag": flag, "entries": entries})
    except struct.error:
        raise CacheError("truncated") from None
    if off != len(body):
        raise CacheError(f"{len(body) - off} bytes left over")
    return boards


def write(boards):
    """The file the game would write for these boards (entries without raw are built from their fields)."""
    out = [struct.pack("<I", len(boards))]
    for bd in boards:
        out.append(struct.pack("<4IBI", bd["cached_at"], bd["leaderboard"], bd.get("a", 4), bd.get("b", 0),
                               bd.get("flag", 1), len(bd["entries"])))
        for e in bd["entries"]:
            if "raw" in e:
                pid, name, block, x, y, z = e["raw"]
                out.append(ENTRY.pack(bytes.fromhex(pid), bytes.fromhex(name), e["rank"], bytes.fromhex(block), x, y, z))
                continue
            up = list(e.get("upgrades", [0, 0, 0, 0])) + [e.get("faults", 0), e["time_ms"],
                                                         e.get("score_value", 360000000 - e["time_ms"]
                                                               - e.get("faults", 0) * 3600000), e.get("bike", 1)]
            block = struct.pack("<8I", *up).ljust(48, b"\0")
            out.append(ENTRY.pack(e["profile"].encode(), e["name"].encode(), e.get("rank", 0), block, 0, -1, 0))
    body = b"".join(out)
    return struct.pack("<4I", VERSION, fletcher32(body, CHECK_SEED, CHECK_MULT), len(body), 0) + zlib.compress(body, 9)


def export(boards):
    """Riders by hash with their best entry per leaderboard (track boards only; Hall of Fame entries give names)."""
    riders = {}
    for bd in boards:
        for e in bd["entries"]:
            if not e["profile"]:
                continue
            h, sha = profile_hashes(e["profile"])
            r = riders.setdefault(sha, {"game_hash": h, "profile_sha256": sha, "name": e["name"], "results": {}})
            r["name"] = r["name"] or e["name"]
            if bd["leaderboard"] == 0 or not e["time_ms"]:
                continue
            new = {"leaderboard": bd["leaderboard"], "track": bd["leaderboard"] & 0xFFFF, "faults": e["faults"],
                   "time_ms": e["time_ms"], "bike": e["bike"], "cached_at": bd["cached_at"]}
            old = r["results"].get(bd["leaderboard"])
            if old is None or (new["faults"], new["time_ms"]) < (old["faults"], old["time_ms"]):
                r["results"][bd["leaderboard"]] = new
    out = []
    for sha in sorted(riders):
        r = riders[sha]
        out.append(dict(r, results=[r["results"][lb] for lb in sorted(r["results"])]))
    return {"format": EXPORT_FORMAT, "format_version": 1, "boards": len(boards), "riders": out}


def load_any(path):
    """An export, from either the cache file itself or an export JSON."""
    data = open(path, "rb").read()
    if data[:1] == b"{":
        exp = json.loads(data)
        if exp.get("format") != EXPORT_FORMAT or exp.get("format_version") != 1:
            raise CacheError(f"{path}: not a {EXPORT_FORMAT} (format 1)")
        return exp
    return export(read(data))


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("show", "export") or (sys.argv[1] == "export") != (len(sys.argv) == 4):
        sys.exit(__doc__)
    boards = read(open(sys.argv[2], "rb").read())
    if sys.argv[1] == "export":
        exp = export(boards)
        with open(sys.argv[3], "w") as f:
            json.dump(exp, f, indent=1, ensure_ascii=False)
        print(f"{len(exp['riders'])} riders, {sum(len(r['results']) for r in exp['riders'])} results -> {sys.argv[3]}")
        return
    for bd in boards:
        when = time.strftime("%Y-%m-%d %H:%M", time.gmtime(bd["cached_at"]))
        print(f"leaderboard {bd['leaderboard']:#x} (track {bd['leaderboard'] & 0xFFFF}), cached {when} UTC, "
              f"{len(bd['entries'])} entries")
        for e in bd["entries"]:
            print(f"  {e['rank']:>6} {e['name']:<20} {e['time_ms'] / 1000:9.3f} s  {e['faults']} faults  bike "
                  f"{e['bike']}  {e['profile']}")


if __name__ == "__main__":
    main()
