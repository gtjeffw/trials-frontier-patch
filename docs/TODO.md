# TODO

## Access lost levels from within the game

Expose levels that are in the game data but unreachable on the map (event-only tracks, ended
seasonal/holiday events, tracks gated behind expired missions) through an in-game entry point,
e.g. a menu or an optional unlock command.

- Selecting them may not be enough: some levels are tied to event logic (special leaderboards,
  collectibles, rally/KTM rules, timed missions, event currencies, scripted triggers in the level).
- Likely approach: build "naked" clones of such levels with the event-specific logic normalised away,
  so they behave like ordinary tracks (own best time, medals, ghosts).
- Inputs we already have: level list (`/conf/levels.txt`), level files (`scripts/level_info.py`, chunk format in
  `docs/JOURNAL.md`), mission definitions (content file 0xc4125fdb), player progress/mission state layout
  (`frida/dump_missions.js`), texture/content pack inventory.
- Keep it optional (separate group or script), never part of the default patch; back up `player.bin` first.

## Other open items

- Load the three untabled texture packs and the Moon content pack directly from the bundle (binary patch), so
  sideloaded iOS installs don't need files in Library/Caches/DLC.
- Touch scaling per axis (float) so any window size / full screen works without the 1366×1024 PlayCover setting.
- Name the 30 June-2017 event ghosts (needs 5.2.0-era event data; not archived as far as we know).
- Check the old iPhone X for a surviving Library/Caches/DLC (would restore lost event art via `--dlc-from`).
- Offline leaderboards / own-ghost racing (see discussion of a local ghost/leaderboard service).
