# Seasonal events (not enabled)

Status (2026-10-10): **set aside.** Events can be brought back, and the most recent Halloween event ran in a test
copy, but none of this is part of any build. This page records how events work in 7.9.0, what a revived event
needs, and the open problems. The working pieces are in [`seasonal-events.example.json`](seasonal-events.example.json)
(a spec fragment that no build reads) and the generic content-patch ops in `scripts/datapack.py`.

## What exists

Every event is still in the game: missions with dates, tracks, models (e.g. `HLW_PUMPKIN_00..02`), text, prizes,
and the code (`SpecialEventManager`, treasure hunt, KTM/rally panels, collectibles, smashables). The events are
dormant only because their date windows (2015-04 .. 2019-12-31) are past. See the journal entries "Seasonal
content: all there, dormant" and "Halloween revival prototype".

## Missions (content file 0xc4125fdb)

Each mission: a header line `id,<c>,NAME_KEY,<category>,<d>,…`, then tagged lines. What was confirmed:

- Header: `<c>` (Mission+0xc) is 2 on missions a character offers (seen on 457 "HERE'S DRACUUL!", with
  `a,2,8,-1`: probably character 8); `<d>` (Mission+0xd) 1 = becomes active as soon as it is available.
- `u` unlock conditions, all must hold (`MissionManager::addAvailableMissions`):
  `u,1,X` mission/reward X completed; `u,3,n,item,sub` item count ≥ n; `u,4,X` mission X completed or active;
  `u,6,f,start,end` Unix time window, f = 0: server-synchronised time (`AntiCheating::getSystemTime`, also valid
  offline), f ≠ 0: device time; `u,10,X` mission flag.
- `t` tasks (e.g. `t,5,…,count,item,sub`: collect `count` of an item), `r` rewards, `c` JSON config (track lists,
  point prizes), `z` timer, `m` map marker.
- `o` overrides: `o,<type>,<track>,<rand>,<p1>,<p2>,<p3>,<p4>,<p5>,"<custom>",<n>`. Struct of 0x40 bytes: type at +0,
  track +4, p1.. at +8, custom data (a `key=value,…` string, keys are hashes) at +0x20, `<rand>` at +0x38.
  `<rand>`: bits 0-2 randomisation type (0 = fixed track), bit 4 use server time, bits 8+ period in seconds.
  Types seen: 7 collectible visible on the track (or, with track 0, collectible id p1 on any track),
  9 smashables on the track (`MissionManager::getVisibleSmashables`), 13 event definition (p1 = panel type; custom
  data: prize lists, sub-missions, …), 16 notification, 18 randomisation condition, 22 Treasure Hunt clue tracks.
- Completion flags: Player+0x3280+id, bit 0. Ids 1-506 are used; the array ends at 511.

## How an event starts

1. `addAvailableMissions` makes a mission available when all its `u` conditions hold and it is not completed;
   with `<d>` = 1 it becomes active (the event mission, e.g. 448, then its sub-missions, e.g. 447).
2. Randomised tracks: when such a mission becomes available, `reserveRandomizedTrackOverrides` reserves save slots;
   while it is active, `updateActiveMissionOverrides` → `updateSavedMissionTime` →
   `updateRandomizedTrackOverrides` rolls the tracks (stored in the save, re-rolled after the period). This works
   offline; it simply never runs for a mission that is not active.
3. The event panel: `MissionManager::getEventPopupMission` is the active mission with a type-13 override; the map's
   `initSpecialEventContainer` builds a panel by its p1. **7.9.0 only builds panels for types 5, 8 (single player /
   treasure hunt) and 6 (KTM)**; types 0 and 1 (2015-era point and percent leaderboard events) are no longer
   created and opening the map crashes (null `MenuzComponentSpecialEventPrizesList`, seen with "Wrath of the
   Pumpkin Queen", type 1). So only the late events (2019: types 5, 6, 8) can come back without new code.
4. Objects on tracks: when a level loads, `GameObjectManager` asks `isCollectibleVisible` (type 7) and
   `getVisibleSmashables` (type 9) of the active missions; only the rolled track shows them.

## The special event button icon

The button (home screen, bottom left; World Map tab) always shows `/MENUZ/ICON/SPECIAL_EVENT_MAP_BUTTON.PNG` from
the bundled `TrialsTexturesDL_special_event.dat`: a fixed name whose art Ubisoft replaced with every event update.
The last build was made for Christmas 2019, so every event shows a holly. The map loads it by a hash written in the
code (`initSpecialEventContainer`), the home screen by name from its layout (content 4b761f6c, button 11).

`event-tab-icon` (in the example spec) lets the running event choose: a 192-byte cave reads the int custom value
`EventTabIcon` (getHashCode 0x6a420739) from the event's type-13 override and uses that texture, otherwise the holly.
Hooked in both places (map: replaces the hard-coded hash; home: `MenuzStateMain::checkSpecialEventPopup` sets the
button's texture id, component +0x40). Without the key nothing changes. The icon itself is made at build time from
the player's own pack (`event_tab_icon` op: the holly button with the holly removed, plus the pack's jack-o'-lantern)
and added to the pack under a new name; the mission names it with `override_custom_param`.

## Halloween Heat (2019): ran in a test copy

Missions 448 "Treasure Hunt!" (event, panel type 5), 447 (daily: hides a track piece, collectible 257, on one rolled
track; four more rolled clue tracks), 457 "HERE'S DRACUUL!" (Count Dracuul offers it; collect pumpkins, item 30/2).
With the example spec's pieces in a copy of the developer's (veteran) save:

- worked: the event started, tracks rolled (hidden item on Pipe Basin; clues Rest in Pieces, Aztec Trance, City
  Hallway, Peak Route), collectible 257 (a pumpkin in the game) was visible only on Pipe Basin and could be picked
  up, Dracuul appeared and his mission was accepted, the map opened with the event panel, the button showed the
  pumpkin on the home screen and the map;
- needed besides the dates: 448 requires item 22/1 ≥ 10 (unknown counter; 0 in that save, only mission 213 grants
  it), dropped with `replace_mission_line`. In the test this was done in memory; the data edit is untested.

## Giant Leaps! (the moon event, July 2019)

Researched 2026-10-10/11 (web sources, nothing downloaded):

- "Giant Leaps!": Ubisoft forum announcement by the community manager, 2019-07-17 (thread 2088777, readable via the
  Wayback Machine). Start 2019-07-18 09:00 UTC, the mission data's start (1563440400); end 2019-08-12 09:00 UTC per
  the mission data, matching players' posts. Game 7.2.x (Android 7.2.0 of 2019-07-15; iOS 7.2.1 of 2019-07-17).
- Story: Professor Looney remote-controls the drone A.N.B.A. on an abandoned lunar colony, riding the event-only Moon
  Rover (bike 12, "PASILA" in the upgrade data, rocket thrusters) to carry Helium-3 ore (an ore meter lost on hard
  landings), three tracks per set rotating every 6 hours, boosters, a "Space Suit" outfit ("Moonrider"). Prizes:
  six tracks (1408-1413: Urban Smash, Dual Snowfest, Fortune Wheel, Blazing Hop, Flora Crossing, High Ville; all in
  7.9.0), two outfits, two paintjobs. Missions 463 (intro, panel type 8) and 464 (the runs; its track list is ~60
  ordinary desert tracks).
- Not lost tracks: July 2019 videos show existing desert tracks (Parched Cliff, Torn Canyon, Ferocious Flips, Wolf
  Den, Dust Bowl, Madhouse, …) with lunar ground, a dome and Earth in the sky. 464's type-4 overrides (503, 504) are
  tutorial ids (`MissionManager::overrideTutorial`, the rocket-thruster tips), not levels.
- The moon environment (`moon_00`: textures, background dome) and the Moonrover ship in 7.9.0; no shipped level uses
  `moon_00`. A level's environment comes only from its own file (`HEAD` byte 4, read by
  `LevelLoader::loadLevel` → `GameWorld::loadResources`; no mission or date override), so the event most likely
  shipped moon versions of those desert level files in its download, replacing the normal ones by name.
- Downloads came from `s3.amazonaws.com/dlcontent_frontier_ios/<version>/info.json` (Android:
  `dlcontent_frontier_android`; the trialstrackmap import scripts document the Android side). Both buckets are gone
  and the Wayback Machine has no copy. Android packages of the period carried only the three base packs.
- With `unlock-special-bikes` the Moonrover can be ridden on any track (crazy-bike leaderboards), in the track's own
  environment.

Sources: the Ubisoft forum thread above; github.com/dutscher/trialstrackmap (MIT; `database/versions.json`, bike and
track ids, categories, import scripts); YouTube event videos of July 2019.

## Holiday decorations

All the holiday objects ship in 7.9.0 and can be placed by any level:
- the common object set (content 0fa1e79a): Halloween bats, spiders, a giant spider, ghosts, a mummy, tombstones,
  cobwebs, a broom, a crow, an eyeball, lanterns, three jack-o'-lanterns, the 2019 `hlw2` pumpkins and balloons, a
  Christmas garland;
- the snow set (60ab5ddf): baubles, wreaths, presents, candy canes, lollipops, a snowman;
- event pickups (c9a215e3): Halloween Heat pumpkins, gift boxes, Easter eggs, the Treasure Hunt track piece, an
  "alien cap";
- textures (Halloween city textures, Christmas garland/baubles), sounds (Halloween ambience, Christmas bells), effects
  (pumpkin, ghost, candy).

Whether ordinary tracks were decorated during holidays (decorated copies in the event downloads, like the moon
versions) or the decorations live only on the year-round themed tracks (Pumpkin Patch, Pumpkin Desert, Ghost Town,
Candyland, Snowman Haven, …) was not checked: decode which shipped level files place these objects.

## If someone picks this up

Bringing holiday events back is a sizeable project and is left for whoever wants it. Leads: the trialstrackmap
maintainer downloaded the game's content for every version in 2019 and may still have the event downloads (the
original decorated/moon level files and event configs); the community's revival efforts (a "Trials Legacy" Discord
was mentioned on Reddit in 2026); old devices whose `Library/Caches/DLC` survived from an event (backups normally
skip caches). Without them, decorated tracks can still be made: level files are readable and all objects ship.

## Open problems before enabling anything

- **Item 22/1**: what it counts, and whether dropping the condition breaks something.
- **Veterans**: missions a player completed years ago stay completed, so the event never offers itself again
  (the developer's save had every 2015 Halloween mission completed). Options: fresh ids (only 507-511 are free,
  five missions, one event at a time) or resetting the flags of the event's missions at the start of each window.
- **Repeats**: a fixed date shift covers one year; a yearly event needs the window moved each year (or a code change).
- **Untested**: finishing the Treasure Hunt (track rewards, bike skins, outfits), Dracuul's pumpkin count and
  rewards, notifications, 6-hour clues (`z,21600`) versus the 24-hour roll seen, behaviour across the window's end.
- **Older events** (types 0/1 panels: Pumpkin Queen, Christmas 2015, …) need panel code or a conversion to type 5/8.
- **Event downloads**: decorated or re-themed track versions and event configs came from Ubisoft's download
  server and are gone (see Giant Leaps! above).
- **Online parts** (event leaderboards such as `ranking/event_stats9`) would need local-services endpoints.

## Tools

- `scripts/datapack.py` content-patch ops: `shift_mission_dates`, `replace_mission_line`, `override_custom_param`
  (mission file); `event_tab_icon` (texture packs, `"textures": true`). Texture packs: `read_texture`, `add_texture`.
- Testing used a separate PlayCover copy (own bundle id) with a copy of a save, and Frida on the running game
  (attach by pid; game-state calls on the main thread via a one-shot hook of `MenuzStateMain::update`; never detach
  while the game runs, which crashed it).
