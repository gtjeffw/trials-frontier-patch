# TODO

## Access lost levels from within the game

Partly done: `open-all-levels` (the game's own cheatOpenAllLevels), `orphan-levels`, `dev-levels`. Still open: play
through event tracks (X-Games, KTM Course, Dakar, Bunker) and see which need their event logic ("naked" clones).

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

## Nothing needed in purgeable storage (installed app: PlayCover and iOS)

Own ghosts and the save live in `Documents/` (never purged, backed up); the game only overwrites an own ghost on a new
best (its delete paths cover mission/PvP/multi-ghost temp files, images, DL content, profile-version reset). The
risk is content: `__getSaveFilePath` type 6 = `NSCachesDirectory + "/DLC"` (purgeable on iOS; also
`DLContentManager::deleteFile(s)`), which is where the untabled swamp/moon/chipshop/Moon packs must be today.

1. ~~**Load untabled packs from the bundle.**~~ — done (compat `dlc-folder-in-bundle`, `bundle_dlc`). Was: patch `__getSaveFilePath` type 6 to `[[NSBundle mainBundle] resourcePath]
   + "/DLC"`; `build_ipa.py` copies the user's own untabled packs (same detection as `install_playcover.py`) into
   `TrialsFrontier.app/DLC/`. Never purged, read-only (game cleanup cannot delete), works for iOS sideloads, and
   makes the PlayCover copy step unnecessary.
2. ~~**Server store in `Documents/LocalServices`**~~ — done (both servers; old Library store moved once): never purged, backed up, second copy
   of every best ghost.
3. ~~**File sharing**~~ — done (`--with file-sharing`). Was: (`UIFileSharingEnabled`, `LSSupportsOpeningDocumentsInPlace`) so users can copy save, ghosts and
   store off the device (the only protection against deleting the app).

## Robot challenge module (daily "beat this rider")

Done (Python server + `inapp/src/TFRobots.m`, parity-tested): `match/v1/robot`, `match/v1/robot_v2`,
`resultservice/v1/robot_replaydata` from the store's ghosts — other riders first (closest just slower than the
player's best), the player's own ghost if no one else. Robots are the "Live Opponents" of the A.N.B.A. quest line
(RobotmanManager). Verified in play: robot ghosts load and are raced (with community bundles too). Still open: how
the PvP duels (`pvp_matches`) could be served.

## Community ghost bundles (self-published, consolidated)

Players publish *their own* runs as GitHub repositories; no central host, each publisher owns their data.
Done 2026-10-10: `scripts/ghost_bundle.py` (export / check / publish / import / search) and the format in
`docs/BUNDLES.md`: GitHub topic `trials-frontier-bundle` for discovery, rider by game hash + sha256 of the profile
id (never the id), optional SSH signature tied to the publisher's GitHub keys, strict validation, import merges
with downloaded opponents by hash. Other riders' ghosts only with `--include-others` (by hash) or
`--include-others-with-names` (plus the names the save keeps for some of them).

- **Contributing without a jailbreak:** unencrypted Finder/iTunes backup of an old device that still has the game →
  `scripts/extract_app_domain.py` → `Documents/player.bin` + `ghost_<hash>_<lb>.bin` → `ghost_bundle.py export`.
  Write a short guide.
- ~~Consolidate many bundles~~ — done: `scripts/community.py` (sources list, cache, layer overlaid by both servers).
  Still open: flag outliers (e.g. far below the 2019 world records); ghost data cannot be fully verified.
- **Announcement / collecting service** (later): receives bundle URLs on publish, or simply crawls the topic.
- Bundles carry ghosts and times only, never game assets.

## Native keyboard and game-controller input (backburner)

The PlayCover fix is the joystick keymap (`scripts/make_keymap.py`, one virtual finger per thumb). Later, for every
platform including iPhone/iPad with a Bluetooth keyboard or controller: read `GCKeyboard` / `GCController`
(GameController framework) in the planned in-app dylib and drive the game's control state directly instead of
synthesising touches. Needs: static analysis of where the touch buttons become throttle/brake/lean (and whether an
analog/tilt lean path exists for sticks), a way to keep touch working alongside, and a key/button mapping UI or
config file.

## Before publishing

- ~~History and licence~~ — done 2026-10-09: names and ids scrubbed from every commit (git filter-repo), commits
  under a GitHub noreply address, MIT licence. Before pushing, search again for personal identifiers (profile ids,
  player names, device ids, local paths) over all tracked files and history.

## Other open items

- ~~**Hall of Fame (overall ranking)**~~ — done 2026-10-10 (see the journal). Was: handle `POST playerstats/v1/stats/global_stats` (after every race:
  {data, drivetime, global_score, upgrades, submittime}) and serve `ranking/global_stats` from it; the displayed
  value (e.g. 1,058,226 for global_score 14.68) needs its conversion decoded. Would give every player a working Hall
  of Fame and likely fix the name a new player sees there in the session where they pick it.

- ~~**Fetch community high scores automatically**~~ — done: the `world-records-2019` source of `community.py`
  (pinned commit and sha256, cached, never breaks anything). Maybe also `database/backup/bonxyResults.json` (another
  leaderboard snapshot) as a further source type.

- ~~Touch scaling for any window size / full screen~~ — works since `screen-size-from-native-bounds`: render size =
  configured window × scaler, touches in window points, so any custom resolution with an integer scaler (2) is fine,
  including full screen. Only a fractional scaler (e.g. 1.5) would still need per-axis float touch scaling.
- Name the 30 June-2017 event ghosts (needs 5.2.0-era event data; not archived as far as we know).
- Check the old iPhone X for a surviving Library/Caches/DLC (would restore lost event art via `--dlc-from`).
- ~~Offline leaderboards / own-ghost racing~~ — done via the opt-in `local-services` group + `server/local_services.py`.

## Local services: personal top five, other riders

- **Top five per track (FRIENDS tab).** The save and the original service kept only one best per leaderboard, so
  history starts now. Have the local server switch on "submit every run" (GlobalSettings 0xd69745a5 = 1, checked in
  `IngameStatePostRace::sendToOnlineLeaderboard`; delivered via the targeting configuration — format still to be
  decoded) and keep the five best runs per track. Show them on FRIENDS as the player plus stand-in riders
  "<name> #2" … "#5" (the leaderboard parser drops repeated profile ids, so each needs its own id and a
  `/v1/profiles` name). Only the best run has a ghost (the game keeps one ghost file per leaderboard and uploads only
  after `"updated"`), so #2–#5 are times without a ghost.
- ~~**GLOBAL tab: the player's single best among other riders.**~~ Done: downloaded opponents + optional 2019
  world records (now a `community.py` source). Candidates: 2019 world records from
  dutscher/trialstrackmap `database/wr/wrrider.json` (MIT; ~360 tracks × iOS/Android × normal/donkey/crazy, rider
  name, bike, faults, time) and its git history (2015–2019 snapshots). World records only, so roughly 2–6 entries per
  track, no ghosts. tf.lforo.com top-10 lists have no licence (ask the owner first). Ask the user before downloading;
  keep third-party data out of the repo unless included with attribution.
- Decide whether the player also appears on FRIENDS when other riders are imported (user preference: yes, with the
  top five there and only the single best on GLOBAL, since GLOBAL auto-scrolls to the player's best).
