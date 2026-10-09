# Formats (Trials Frontier 7.9.0, iOS)

All integers little-endian. Function names/addresses refer to the 7.9.0 executable.

## String / file-name hash — `mt::String::getHashCode` (0x100019bd0)

```
x = 0; n = strlen(s)
for each byte c (signed char): x += n * c; n = (n & 0xffff) * 18000 + (n >> 16)   # 32-bit wraparound
```
Used for datapack file names (`/conf/levels.txt` → 0xa2263380) and localisation keys
(`LVL_FANG_WALL` → 0x5d9a9992).

## player.bin — `tr::Player::load` (0x1001c9e98) via `mt::file::SaveFile`

1. Obfuscation (`SaveFile::open`): for each byte `b ^= key & 0xff; key = key * mult` (32-bit), starting with
   `key = seed`. `Protection` for player.bin at 0x100af1ff0: seed 0x9D, mult 0x20B9 (+ 0xEC51ED, 0x24D7 used by
   the checksum).
2. Header (`SaveFile::processHeader`): u32 version (114), u32 fletcher32 checksum, u32 uncompressed size, u32 0.
3. Body: zlib (`SaveFile::uncompressFile`) when size ≠ 0.

Decoded body (42,792 bytes for version 114) is read field by field by `tr::Player::load`; profile name near the
start, then inventory, progress (`tr::PlayerProgress::readFrom`), scores (`tr::Player::loadScores`), …

### Score table — `tr::Player::loadScores` (0x1001c9298)
u32 count, then per record: u32 leaderboard id, 60-byte `tr::PlayerScores` (as u32 after the id):

| idx | meaning |
|---|---|
| 0 | marker (low byte 0xff) |
| 7 | faults |
| 8 | best time, ms |
| 9 | 360000000 − time − faults × 3600000 (integrity copy; faults outrank time) |
| 10 | bike id |
| others | not yet identified (2: 0/1, 3–6: often 10,10,10,10, 14: 49/50) |

Leaderboard id = track id for the default bike class, else `track | (0x10000 << (bikeClass − 1))`
(`tr::LeaderboardManager::getLeaderboardId`). Events/weekly challenges use mission/server ids.

## Ghost replays — `Documents/ghost_<playerHex>_<leaderboardId>.bin`

16-byte header: u32 version (2 or 3), u32 hash, u32 uncompressed size, u32 0; then zlib.
Payload v2: u32 time ms, u32 sample count, samples…; v3: u32 bike id, u32 time ms, u32 sample count, samples…
Samples are ~133 ms apart and encoded as small deltas (format not yet decoded).
`robot_ghost-*.robot` (downloaded opponents) use the same container with version 3.

## Datapacks — `data/TrialsMobile/*.dat` (`datapack::DataPack`)

Header: u32 magic, u32 count, u32 entry size (12). Entries: u32 ?, u32 data offset, u32 name hash.
Data area starts at 12 + count × 12. Each file: u32 stored size, u8 compression (1 = zlib, 0 = raw), 3 bytes,
then payload.

## Level list — `/conf/levels.txt` (JSON)

`Levels[]`: `N` name key, `ID`, `D` difficulty, `M0`–`M3` medal time limits (ms), `F0`–`F3` fault limits,
`F` source level file, `A` author, map position `X`/`Y`, others. Medal = first tier i with
`time ≤ Mi and faults ≤ Fi` (tier order confirmed in game; top tier name assumed "platinum").

## Localisation — `/gen/lang/<language>_strings.bin` (LOCF)

u32 "LOCF", u8 version, u32; then entries: u32 key hash, u16 length, UTF-8 text (NUL-terminated).

## Missions — content file 0xc4125fdb (CSV-like)

Mission header line `id,…,NAME_KEY,…`, followed by typed lines (`t` task, `u` unlock, `r` reward,
`o` override, `c` JSON config). Override type 13 (`o,13,…`) carries event parameters keyed by hashes.
7.9.0 only contains 2019-and-later events.
