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

## Open problems before enabling anything

- **Item 22/1**: what it counts, and whether dropping the condition breaks something.
- **Veterans**: missions a player completed years ago stay completed, so the event never offers itself again
  (the developer's save had every 2015 Halloween mission completed). Options: fresh ids (only 507-511 are free,
  five missions, one event at a time) or resetting the flags of the event's missions at the start of each window.
- **Repeats**: a fixed date shift covers one year; a yearly event needs the window moved each year (or a code change).
- **Untested**: finishing the Treasure Hunt (track rewards, bike skins, outfits), Dracuul's pumpkin count and
  rewards, notifications, 6-hour clues (`z,21600`) versus the 24-hour roll seen, behaviour across the window's end.
- **Older events** (types 0/1 panels: Pumpkin Queen, Christmas 2015, …) need panel code or a conversion to type 5/8.
- **Online parts** (event leaderboards such as `ranking/event_stats9`) would need local-services endpoints.

## Tools

- `scripts/datapack.py` content-patch ops: `shift_mission_dates`, `replace_mission_line`, `override_custom_param`
  (mission file); `event_tab_icon` (texture packs, `"textures": true`). Texture packs: `read_texture`, `add_texture`.
- Testing used a separate PlayCover copy (own bundle id) with a copy of a save, and Frida on the running game
  (attach by pid; game-state calls on the main thread via a one-shot hook of `MenuzStateMain::update`; never detach
  while the game runs, which crashed it).
