# Adding a mission

How to add a mission to Trials Frontier 7.9.0 at build time, worked out from the code (2026-10-16). Working example:
mission 507 in group `story-extras` of `patches/trials-frontier-7.9.0.json` (its mission block, its texts in all
eleven languages, and an unlock condition set by a small code patch). Line formats not listed here are in
[EVENTS.md](EVENTS.md).
Function addresses refer to the decompiled 7.9.0 executable.

## Recipe

1. **Pick an id from 507 to 511.** Ids 1-506 are taken; ids above 511 are fatal ("Invalid Mission ID",
   `MissionDBLoader::addNewMission` 0x100204808), and the table (`MissionDB::init`) and the solved flags
   (Player+0x3280+id) end at 511. The game looks missions up by id, so the block can go anywhere.
2. **Write the block** and add it with the content-patch op `add_mission` (mission file, `file_hash` c4125fdb):
   ```
   <id>,<c>,MISSION_<id>_NAME,<villager>,<d>,0,0,0,0
   t,...   (at least one task)
   u,...   (unlock conditions, all must hold)
   r,...   (rewards)
   ```
   `add_mission` writes the file's CRLF line ends (the parser skips each line end as two bytes) and refuses what the
   parser would choke on: unknown line types (they hang the parser), more than 6 t / 8 r / 4 u / 8 o / 4 m lines (no
   bounds checks in `Mission::add*`), task type > 29, reward type > 1, unlock type > 10.
3. **Add its texts to every language table** with `add_mission_strings` (`files`: all eleven
   `/gen/lang/*_strings.bin`; list in `datapack.LANGUAGES`). The game looks up only the NAME key and takes the
   other texts **by position** after it: DESC (offered), MISSION (in progress), REW (solved), FAIL, and one spare.
   A missing NAME key falls back to position 0, i.e. someone else's text. Pages are separated by `|`, `{c1}...{c0}`
   highlights.
4. **Keep it in every later build.** If a save has the mission available or active and a build without it runs,
   the Saloon reads the missing mission without a null check (`setMissionsToVillagers`) and crashes. So add missions
   in default groups, or make sure they can only ever be offered by builds that keep them.

## The fields that matter

- **Header** `id,c,NAME,villager,d,f6,f7,f8,f9` (`Mission::setup` 0x1001ed2f4):
  - **villager** (+0x14): who offers it, by index in `/conf/villager_bounds.txt`: 0 the Lady (barkeep),
    1 garage, 2 teddy kid, 3 feather, 4 store, 5 forge, 6 tech girl, 7 trick kid, 8 cat, 9 Butch, 10 the
    Ghost, 11 Leroy, 12 Cassidy, 13 slot machine, 14 Robotman, 15 PvP lady, 16 event villager, 17 terracotta
    soldier, 18 sun god, 19 cowgirl, ... The card's portrait is
    `/MENUZ/MISSIONS_RGBA8/MISSIONS_CHARACTERS_<villager+1>_LARGE.PNG`. The `j,<n>` lines there are sound ids.
  - **c** (+0xc): slot class. A mission is not offered while an *active* mission has the same villager and c.
  - **d** (+0xd): 1 = active as soon as available, no card to accept; 0 = offered as a card.
  - f6 non-zero hides the villager's mission; f7 is parsed and ignored; f8 is a content revision (keep 0); f9 0.
- **Card placement:** `MenuzStateMissionHall` is the Saloon. Each time it opens, `assignMissionToVillager`
  (0x100245a00) gathers available and active missions (64 slots each) and keeps **one card per villager**: an active
  one wins, else the one with the smallest unlock-tree depth. Any villager can stand in the Saloon.
- **`a` line** (optional): what the accept button does. No `a` line = close the bubble and stay in the Saloon;
  `a,1,...` starts the level; `a,2,8,p` goes to the map; `a,2,42,...` the inventory.
- **`b` line** (optional) flags: 8 hides it from the active-missions list, **16 hands out rewards automatically and
  hides it from the Saloon**, 256 needs valid anti-cheat time; avoid 16 for a card.
- **Tasks** `t,type,completion,p3,p4,p5,p6`: completion 0 = current state. `t,5,0,0,<count>,<item>,<sub>`
  (collect items) with count 0 is always satisfied: accepting completes the mission at once. A mission with **no
  task** completes on accept but its card ends up with no text and no reward popup, so always give it one.
- **Rewards** `r,0,<item>,<sub>,<amount>,<when>,1`: coins `r,0,0,1,N,0,1`, gems `r,0,0,2,N,0,1`, XP item 70;
  when 0 = on completion (through the reward popup), 1 = on accept.
- **Unlocks:** `u,1,X` X solved and its reward collected; `u,4,X` X collected or active; `u,3,n,item,sub` item count
  at least n; `u,6,f,start,end` time window; `u,10,X` X's completion flags.

## The flow of an offered mission

Tap the card: the bubble shows DESC. Accept: the mission becomes active (`setMissionActive` 0x100249310), on-accept
rewards are paid, and if every task already holds it is solved at once; the bubble then shows REW with sparkles. Tap
again: `PopupStateMissionCompleted` pays the on-completion rewards (`giveRewards` 0x10030d28c) and removes the
mission from both lists; the Saloon is rebuilt and the card is gone.

## Mission 213, "THE END"

The Lady's last card (villager 0, `b,10`) needs one of item 22/1 collected after accepting, and nothing but its own
reward grants 22/1, so it can never be solved: it stays on offer (DESC) or active (MISSION text) for good. Item 22
holds miscellaneous flags (sub 0 last purchase time, 2/3 social links, 4 random missions); sub 1 is never granted by
the code, which is why other missions use `u,3,n,22,1` as a permanent off switch. Its texts are keyed MISSION_296_*.

## Offering a mission only to veterans

Unlock conditions can test items, missions and dates, but not *when* a mission was solved. Mission 507 is meant for
players who had finished the story in the original game, not those who finish it in the patched one, so the
`story-extras` group sets a marker once, when the patched game first meets a save:

- **Where:** the single exit of `tr::Player::checkPlayerProfileVersion` (hook 0x1001cd0a8, cave 0x100006d60). It runs
  after every save load (`Player::load`, from `GlobalData::init` and `switchLocalProgress`), also for a new player
  with no save, and on every main-menu activation; x19 holds the Player.
- **What:** item 126 sub 0 (never used by the game; all 280 items x 5 subs are saved). While it is 0 it becomes 2 if
  the story's final race (mission 212, solved flag Player+0x3280+212 bit 0) is already done, else 1, and the
  "save needed" bit Player+0x6de4 is set as the game does after its own version write.
- **Then:** mission 507 has `u,3,2,126,0`. A new player gets 1 before their first race and keeps it, so finishing
  the story later never offers it. A save that finished the story in a build of this patch from before the
  marker (2026-10-16) is counted as a veteran.
- **Resets:** anything that resets the items (new game, account switch, a server progress restore) clears the marker,
  and the next check sets it again from the progress at that moment. The account switch is disabled
  (`local-services-keep-account`) and the local servers do not serve progress restores.
