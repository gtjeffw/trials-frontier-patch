# trials-frontier-patch

Trials Frontier was an excellent game in the Trials series by Ubisoft RedLynx. Unfortunately, it is no longer
available. Even if you got this free-to-play game while it was still being distributed and supported, you can no
longer play it, because Ubisoft shut down its servers, and they don't allow offline play. It doesn't matter how much
blood, sweat, tears, or money you spent on the game. However...

![Trials Frontier 7.9.0 running again on a Mac in PlayCover](docs/images/trials-frontier-patched.jpg)

This project lets you ride again! And running from *your own* save game data in **Trials Frontier 7.9.0** for iOS!
It builds a patched app that:

- **Plays on a Mac or an iPhone/iPad.** Runs on an Apple-silicon Mac in [PlayCover](https://playcover.io) with
  keyboard controls, or sideloaded on an iPhone/iPad with a free Apple ID.
- **Brings back your old save.** Progress, bikes and best times, provided they are still on your iPhone/iPad or in a
  backup of it. Expect ghosts for only some of your best times: a ghost file was only written on the device where
  you set that best. Online, your own ghost came from Ubisoft's server, so bests that reached a device through cloud
  sync never had a file there.
- **Keeps your data safe on iPhone/iPad.** Content packs the game would only load from its cache folder ship inside
  the app, so iOS can't clean them up. With the `file-sharing` option, your save and ghosts show up in Finder and the
  Files app for easy copying.
- **Works fully offline.** Ads, tracking and every connection to Ubisoft/RedLynx are disabled.
- **Leaderboards and ghost races work again.** An internal server replaces Ubisoft's shut-down servers, so
  leaderboards, the Hall of Fame and ghost races work locally.
- **Other riders to race.** Your downloaded opponents, other players' published ghost bundles, and the 2019 world
  records.
- **New players welcome.** A fresh game works too, and you can play through the story. You'll miss out on bonuses for
  online activity like linking a Ubisoft account or sharing on Facebook, and on PvP duels. However...
- **No grind, if you like.** Opt in to quality-of-life features: unlimited fuel, unlimited gems, buy coins with gems,
  unlock every bike, open every level that can no longer be unlocked, and more (see *Options*)! Or leave them out for
  the original challenge: the game's own fuel timer and gem income work offline.

You can also share your own runs with other players as a ghost bundle. In fact, this project can help you publish
your bundle in a way that lets fans consolidate high scores and ghost runs and begin to rebuild global data for
friendly competition: high scores, and racing ghosts either from high score lists or in A.N.B.A. challenge races.
This is an unofficial fan project; the repository contains no game files (see *Legal*).

## Quick start

1. **Keep your old game data safe** on every iPhone/iPad that still has the game, e.g. one dug out of a drawer
   (details: [Keeping your old game data safe](#keeping-your-old-game-data-safe)). Read that section first; the gist:
   don't start the old Trials Frontier app, stop the device from updating itself, and back it up to your Mac.
2. **Get the game files** from a copy of the game (preferably your own): the app and an unencrypted copy of its
   executable.
   **Note:** this project can't tell you how to get an unencrypted copy. That is up to you, after checking whether
   you are allowed to in your country (details: [Getting the game files](#getting-the-game-files)).
3. **Build and install** the patched game into PlayCover with one command
   ([Building and installing](#building-and-installing)).
4. **Bring in your save**, or start fresh ([Your save, or a fresh start](#your-save-or-a-fresh-start)).

You need an Apple-silicon Mac with [PlayCover](https://playcover.io), Xcode (for its compiler) and Python 3.12. For
iPhone/iPad instead of a Mac, see *iPhone / iPad*. In this repository's folder:

```
# Your old data: take the game's files out of an unencrypted backup of your device
python3 -I scripts/extract_app_domain.py <backup folder> <my trials data>

# Other riders: fetch the patch author's best times and ghosts and the 2019 world records, merge them
python3 -I scripts/community.py sync
python3 -I scripts/community.py build

# Build: patch your copy of the game with the recommended options and those riders, install it
python3 -I build.py --app <TrialsFrontier.app> --work <work folder> --decrypted <unencrypted TrialsFrontier> \
    --with unlimited-fuel,unlimited-gems,coins-for-gems --community --install --keymap

# Your save: start the game once in PlayCover, close it, import your save (skip for a fresh start)
python3 -I scripts/import_save.py <my trials data>/AppDomain-com.ubisoft.redlynx.trialsfrontier/Documents
```

## Keeping your old game data safe

Your progress, best times and ghosts live only on the devices you played on. Protect them before anything else:

- **DON'T RUN Trials Frontier** on the old device. Each start tries to reach Ubisoft's servers and can change local
  data: a running game rewrites its save, and a login reset clears cached data such as friends' times. Your data is
  safest exactly as it is now.
- **Turn off updates before anything else.** A device that has been in storage will want to update as soon as it
  is online. A newer iOS may no longer run the old app, and updates close the routes some people use to get the
  game files off a device; an update cannot be undone. Airplane Mode first (Control Center), then Settings →
  General → Software Update → Automatic Updates: turn off downloading and installing. An update that was already
  downloaded can be deleted in Settings → General → iPad (iPhone) Storage. Keep Airplane Mode on until the backup
  is done (a backup over a cable works without Wi-Fi).
- **Don't delete or offload the app.** It can no longer be downloaded. iOS can offload apps on its own when storage
  runs low: Settings → App Store → Offload Unused Apps: off (older iOS: Settings → iTunes & App Store).
- **Back up the device to your Mac** with a cable: Finder (or Apple Devices on Windows) → your device → "Back up all
  of the data on your iPad to this Mac", **Encrypt local backup** off → Back Up Now. Unlock the device and tap
  "Trust" when asked. (If encryption was already on, turning it off asks for the password that was set back then.)
  Then take the game's files out of the backup:

  ```
  python3 -I scripts/extract_app_domain.py <backup folder> <output folder>
  ```

  Finder keeps backups in `~/Library/Application Support/MobileSync/Backup/<a long device id>`: that folder is
  `<backup folder>` (the newest one, if you backed up several devices). macOS only lets Terminal read it with Full
  Disk Access (System Settings → Privacy & Security → Full Disk Access); or copy the folder elsewhere in Finder
  first.

  Its `AppDomain-com.ubisoft.redlynx.trialsfrontier/Documents` folder holds what matters: `player.bin` (your
  progress and best times), `ghost_<id>_<track>.bin` (your own ghosts) and `robot_*` (the opponents the game
  downloaded). A backup does not contain the app itself or its download cache.
- **Keep that original untouched.** Finder replaces a device's backup the next time it backs up that device; to keep
  this one, Finder → your device → Manage Backups → right-click it → **Archive**. Also put a copy of the extracted
  folder somewhere safe (an external drive, a zip in cloud storage) and treat it as read-only: `import_save.py` only
  copies from it, and the patched game always plays on its own copy, never on your original.
- **Friends' times may survive in a cache.** The game kept the friends tab of every leaderboard you opened in
  `Library/Caches/lbstorage.bin`: names and best times. Backups leave caches out, so this only helps where the old
  game's data is still on disk, e.g. an Apple silicon Mac that ran the App Store version:
  `~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Library/Caches/lbstorage.bin`. Copy it before
  starting any game there (PlayCover uses the same folder, and the game empties the file when its login resets),
  then see *Other riders*.
- **Back up every device you played on.** If your progress synced between, say, an iPad and an iPhone, together
  they hold more than either one alone:
  - **Ghosts stay on the device you rode them on.** A ghost file was written only on the device where you set that
    best (online, your own ghost came from Ubisoft's server), so each device has ghosts the other lacks.
  - **Downloaded opponents** are per device too: each kept the other riders' ghosts it raced against.
  - **Best times** synced, but each save is only as current as that device's last sync, so one may hold bests the
    other never got.

  Import one save first, then add the others: their best times, ghosts and opponents are merged, keeping the best
  of everything ([Your save, or a fresh start](#your-save-or-a-fresh-start)). Even so you will likely find ghosts
  for only some of your best times.

## Getting the game files

You need two things from **a copy** of Trials Frontier 7.9.0 (preferably your own; arm64, as installed on a 64-bit
iPhone or iPad):

1. **The app bundle** `TrialsFrontier.app`: its content packs, artwork and settings. It is not in a device backup;
   it has to come from a device you can access directly.
2. **An unencrypted copy of its executable.** App Store apps are protected with Apple's FairPlay encryption on the
   device, so the executable inside the bundle cannot be patched as it is. There are well-established community
   methods to jailbreak an older iOS device and decrypt apps installed on it, for example an old iPhone or iPad
   that still has Trials Frontier installed. This project does not provide or link to such tools.

**Make your backup first** ([Keeping your old game data safe](#keeping-your-old-game-data-safe)), whatever you do to
get these: some ways of getting the files start the app, and a started game can change its data.

**Check your local laws and regulations first.** In many countries, circumventing copy protection is restricted
even for software you own (for example the US DMCA, section 1201, or the EU's Copyright Directive), with
exceptions that differ from country to country. Whether and how you obtain an unencrypted copy is your own
decision and responsibility.

**Content packs.** The app carries 42 content packs (`data/TrialsMobile/*.dat`: levels, bikes, artwork, sounds).
The build checks yours against the reference copy and lists any that are missing or different; you'll need to find
another source for missing ones. Without `content.dat`, `contentSFX.dat` and `textures.dat` the game cannot start;
others missing leave parts of the game without their tracks, sounds or artwork. Three packs the game only ever
downloaded (`TrialsContentDL.dat`, `TrialsContentDL2.dat`, `TrialsContentOfferDL.dat`) are gone and not needed.

## Building and installing

In this repository's folder:

```
# other riders: fetch the sources into a local cache (checked), then merge them into a community layer
python3 -I scripts/community.py sync
python3 -I scripts/community.py build
# patch, package and install into PlayCover:
#   --app        the app bundle from your copy (Getting the game files)
#   --work       a folder for the build's files, outside this repository
#   --decrypted  the unencrypted executable (Getting the game files)
#   --with       options: unlimited fuel and gems, and buy coins with gems; see Options
#   --community  build the layer from the line above into the game
#   --install    hand the result to PlayCover;  --keymap  install the keyboard controls
python3 -I build.py --app <TrialsFrontier.app> --work <work folder> --decrypted <unencrypted TrialsFrontier> \
    --with unlimited-fuel,unlimited-gems,coins-for-gems --community --install --keymap
```

Your save is not part of the build: it goes into the game's data folder, which PlayCover creates on the game's
first start ([Your save, or a fresh start](#your-save-or-a-fresh-start)).

This is the recommended game: the whole story as designed, without the grind that once pushed players towards
real-money purchases.

- **Unlimited fuel and gems** (`unlimited-fuel`, `unlimited-gems`), and `coins-for-gems` lets you buy coins with them
  (otherwise the coin packs are dead App Store purchases). Bikes, upgrades and levels are still earned by riding.
  For the original challenge leave out `unlimited-fuel` and/or `unlimited-gems`: fuel refills over time and gems are
  earned by playing, as designed, all offline; only the old extra gem sources (purchases, video ads, Facebook and
  Ubisoft bonuses) are gone.
- **Leaderboards with riders from day one:** the first two lines fetch the patch author's best times and ghosts
  (`gtjeffw/trials-frontier-ghosts-jayuph`, including 383 opponents that game had downloaded) and the 2019 world
  records; `--community` builds them into the game.
- `build.py` checks your files, patches the game, builds the in-app server, packages an `.ipa` and hands it to
  PlayCover. It keeps your work files in `<work folder>` (outside this repository).

**Everything unlocked instead:** add `unlock-bikes,unlock-legendary-bikes,unlock-special-bikes` to `--with` for every
bike right away, and `open-all-levels` to reveal every level (some event tracks behave oddly); see *Options*.

Then, in PlayCover's settings for the game:

- **Resolution: Custom**, your screen's size in points: scaling 2 on a Retina screen (e.g. 1512×982 on a 14" MacBook
  Pro), 1 on a regular external monitor (e.g. 1920×1080).
- **Keymapping** on: arrow keys or WASD to ride, Space to restart, Esc to pause.
- Full screen (green button) fills the display. With two displays, play on the **main** one (System Settings →
  Displays → "Use as main display"); on another display with a different refresh rate, motion judders.

Closing the game's window quits it.

**Rebuilding later** (other options, a newer version of this patch) works the same way and keeps your
progress: PlayCover replaces only the app, not your save. Close the game first; `build.py --install` refuses to
replace a running game.

## Your save, or a fresh start

**Fresh start:** just play. The tutorial runs, you pick a rider name, and the story begins.

**Your old save:** start the patched game once (so PlayCover creates its data folder), close it, then:

```
python3 -I scripts/import_save.py <the Documents folder from your backup>
```

It checks the save, moves the game's current data aside (nothing is deleted) and copies in your save, ghosts and
opponents. On its next start the game is yours again, and the leaderboards show your best times and ghosts.

**More later:** add another device's save (e.g. the iPhone you also played on), or a friend's, at any time; your
own save stays as it is:

```
python3 -I scripts/import_save.py --add <another Documents folder>
```

Every start of the game merges the added saves, keeping the best of everything: your own runs from another device
count as yours, someone else's appear as a rider with their name, and the opponents they downloaded join yours.
Riders known only by number get their names as soon as any save or bundle names them.

**Back up the patched game too.** From now on your progress lives in the game's PlayCover data,
`~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Documents`. Copy that folder now and then, with the
game closed, for example before rebuilding:

```
ditto ~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Documents ~/trials-backup-$(date +%Y%m%d)
```

## Good to know while playing

- **Old online features: best skipped.** The game still shows its old online buttons and prompts: joining or logging
  in to Ubisoft (Uplay), Facebook, adding and inviting friends, gifts, real-money purchases, video ads, sharing. They
  talked to services that no longer exist; at best nothing happens, possibly an error or a stuck screen. Nothing in
  the game needs them.
- **PvP duels are not available.** From player level 10 a character in the saloon leads you to the War Room, which
  shows a loading spinner; tap **Home** to leave. Nothing in the story needs PvP; skip the occasional random "win
  PvP races" job.
- **Back up before rebuilding mid-game.** Rebuilding or importing a save in the middle of the story has worked in
  testing, but whether it can upset a half-finished mission is not known. If your save matters, copy
  `~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Documents` first, and rebuild between missions.
- **Special bikes** (Stallion, BMW, Moonrover, Donkey) have their own leaderboards. Moonrover, the jetpack rover of
  2019's moon event, is chosen for a level on the map; its garage card stays empty.
- **New text in other languages.** Where this patch adds text to the game, it was written in English and translated
  into the game's ten other languages by Claude, an AI (LLM) agent. We apologise for any clumsy or wrong
  translations; corrections from native speakers are very welcome.

## Options

| `build.py` | what |
|---|---|
| `--with unlimited-fuel` | races never use fuel. Without it, fuel refills over time (full rider outfits refill faster), or buy refills with gems |
| `--with unlimited-gems` | gems always show 9999. Spending still comes off your real balance (never below 0) and earned gems add to it, so leaving the option out later starts from what is left. Without it, gems are earned in missions, quests, levels and achievements |
| `--with coins-for-gems` | coin packs (App Store only) become gem-priced shop items, priced like the gem pack of the same tier |
| `--with unlock-bikes` | unlocks the regular tier 1–3 bikes (Armadillo … Phantom, Bandito); upgrade them in the game |
| `--with unlock-legendary-bikes` | unlocks the legendary bikes: KTM 500 EXC, KTM 450 RALLY, BMW F800 GS, HD, HD EV |
| `--with unlock-special-bikes` | unlocks the special bikes: Stallion (horse), BMW, Moonrover (jetpack), Donkey |
| `--with open-all-levels` | the game's own developer switch reveals every level on the map (event, X-Games, Bunker tracks …); levels with event rules may behave oddly |
| `--with orphan-levels` | gives the six levels without a map position a place in the main map's fogged east |
| `--with dev-levels` | names and places six unfinished developer test levels that ship with the game |
| `--with file-sharing` | shows the game's data (save, ghosts, server data) in Finder and the Files app; for iPhone/iPad |
| `--community [<layer>]` | build other riders into the game (see *Other riders*) |
| `--avatars <dir>` | `<profileId>.png` (146×146) pictures for the leaderboards, e.g. your own Ubisoft avatar |
| `--bundle-id`, `--display-name` | a second copy next to the first, with its own data (e.g. a fresh game besides your own) |
| `--server embedded` (default), `external`, `none` | where the game's server runs: inside the app, run by you (development), or none (no leaderboards or ghosts) |

## iPhone / iPad (sideloading with a free Apple ID)

```
python3 -I build.py --app <TrialsFrontier.app> --work <work> --decrypted <executable> \
    --with file-sharing,unlimited-fuel,unlimited-gems,coins-for-gems --community \
    --bundle-id com.<you>.trialsfrontier --display-name "Trials Offline"
python3 -I scripts/sign_ios.py <work>/TrialsFrontier-7.9.0-patched.ipa <work>/signed
python3 -I scripts/ios_device.py install <device> <work>/signed/TrialsFrontier.app      # iOS 17+
ideviceinstaller -u <udid> install <work>/signed/TrialsFrontier-7.9.0-patched-signed.ipa # older iOS
```

Once: sign in to Xcode with your Apple ID, create any iOS app with the same bundle id and your Personal Team, and run
it on each device (this registers the device and creates the certificate and profile). The app installs next to the
original. Your save: `scripts/ios_device.py push-data` (iOS 17+) or drag the files in with Finder (file sharing).
Free signatures last 7 days: re-run `sign_ios.py` and reinstall; the game's data stays. If there is no sound, check
the silent switch.

## Sharing your ghosts

Publish your best times and ghosts as a *bundle*, a public GitHub repository, so other players can race you. A
bundle never contains your save, your profile id or any game file (format: `docs/BUNDLES.md`).

**You need** a GitHub account and the GitHub CLI, logged in:

```
brew install gh
gh auth login                        # the web login is fine
```

**Publish** from your game's data (the PlayCover copy holds your old save plus everything you have ridden since):

```
python3 -I scripts/ghost_bundle.py export ~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Documents \
    ~/trials-bundle --app <TrialsFrontier.app> --include-others
python3 -I scripts/ghost_bundle.py publish ~/trials-bundle --dry-run    # a preview folder; publishes nothing
python3 -I scripts/ghost_bundle.py publish ~/trials-bundle
```

- **Choices when exporting:** `--app` adds track names. `--include-others` adds the other riders' ghosts your game
  downloaded, by number only (their names come from their own bundles); `--include-others-with-names` adds the names
  your save knows for some of them, which is your call. `--license CC0-1.0` (the default: anyone may use them) or
  `CC-BY-4.0` (credit required). `--name` and `--avatar <png>` set the name and picture others see.
- **What is published:** your rider name, best times and ghosts, two one-way hashes of your profile id (they let the
  game and other bundles recognise you without revealing the id), your picture if any, and with `--include-others`
  the opponents' ghosts. `publish` shows all of it and asks you to type "I agree".
- **Where:** `<you>/trials-frontier-ghosts-<name>`, every commit signed by GitHub for your account (the proof that
  the bundle is yours). `publish` then offers to list it in the community registry
  ([gtjeffw/trials-frontier-registry](https://github.com/gtjeffw/trials-frontier-registry)), so other players get it
  automatically; the registry also finds bundles by themselves within a day.

**New best times later:**

```
python3 -I scripts/ghost_bundle.py update ~/trials-bundle
```

It repeats your first export's choices, keeps the best of old and new, shows what improved and publishes. **Keep the
bundle folder**: it remembers those choices (in `.export.json`, never published). If you lose it, export again into a
new folder and publish with `--repo trials-frontier-ghosts-<name>` to the same repository. `--documents <folder>`
takes the update from another copy of your game, e.g. an iPhone's data.

## Other riders

`scripts/community.py` brings other riders into your game: every bundle listed in the community registry, the patch
author's bundle, and the 2019 world records from [dutscher/trialstrackmap](https://github.com/dutscher/trialstrackmap)
(MIT). Each bundle is downloaded and checked on your Mac, then all of them are merged into a *community layer* that
the game's server reads. Your own results are never changed by it.

```
python3 -I scripts/community.py update            # fetch, check, merge, install (close the game first); again any time
python3 -I scripts/community.py list              # what is included
python3 -I scripts/community.py disable <id>      # e.g. world-records-2019, registry, or one bundle (owner/repo)
python3 -I scripts/community.py add <owner>/<repo>   # a bundle the registry does not list; discover --add finds all
python3 -I scripts/community.py add <lbstorage.bin>  # friends' names and times from a leaderboard cache
```

- **A second copy** of the game (`--bundle-id`):
  `community.py update --container ~/Library/Containers/<bundle id>/Data`.
- **iPhone/iPad:** build the layer in with `build.py --community`, or copy it with `scripts/ios_device.py push-data`.
- **Trust:** a bundle from GitHub is used only if every commit was made through GitHub by the publisher it names
  (signed by GitHub). `add --unsigned-ok` accepts one that is not; local folders are not checked. The registry only
  points to bundles, so it cannot slip in data that does not pass these checks on your Mac.
- **Leaderboard caches** ([Keeping your old game data safe](#keeping-your-old-game-data-safe)) add your old friends'
  names and best times, and the names also stick to their downloaded ghosts. To share one, export it first
  (`scripts/lbcache.py export <lbstorage.bin> <out.json>`): like a bundle's other riders, the export carries hashes
  instead of profile ids and no names (`--with-names` adds them); `community.py add` takes the export too.

Each source keeps its own licence (bundles: chosen by their publishers; the world records: MIT). Playing with them
is fine; if you republish the data, pass on a layer or an app with one built in, or serve it publicly, check and
honour every source's licence: `community.py build` prints them and writes `NOTICE.md` into the layer
(`docs/BUNDLES.md`, *Licences*).

## Status

Tested with PlayCover on macOS and sideloaded on an iPhone 15 Pro (iOS 26) and an iPad Air 2 (iOS 15): the whole game
plays offline with keyboard controls, for a restored profile and for a brand-new player (tutorial, naming, story,
daily quests); leaderboards and the Halls of Fame with your own results, downloaded opponents, shared bundles and
the world records; racing and uploading ghosts; A.N.B.A.'s live opponents; generated avatars; coins for gems; bike
unlocks; hidden, orphan and developer levels. Open items (PvP duels, top five on FRIENDS, event tracks, holiday
events, native keyboard/controller input, a guide for players without a jailbreak) are in `docs/TODO.md`.

## For developers

### How the patch works

Every patch is data in `patches/trials-frontier-7.9.0.json`: address, original and new bytes, and the reason. The
default groups are `compat` (runs outside a team-signed install, without the dead content bucket), `privacy` (ads,
cross-promotion and analytics SDKs off), `offline` (no Ubisoft/RedLynx services; the online code itself is kept, so
a fan server could replace this group) and `story-extras` (small content additions; see `docs/MISSIONS.md`).
`local-services` and `embedded-server` add the game's own server; the rest are the options above.

`build.py --decrypted <executable>` checks what you give it before patching anything: the right build (Mach-O UUID),
not encrypted, the formerly encrypted code identical to the reference, and every patch site holding exactly the
original bytes. An executable byte-identical to the reference gives byte-identical builds, checked against the
recorded hashes; one from another tool that differs only in details such as its code signature is accepted too.
Packs from a device's download folder (`Library/Caches/DLC`) can be added with `scripts/install_playcover.py
--dlc-from <folder>`.

### Local services

With `local-services` the game logs in silently, fetches its configuration and talks to its game server, all on
`127.0.0.1`; the app may not reach any other host (the HTTP layer only allows `http://127.0.0.1:` URLs and
`getaddrinfo` only resolves `127.0.0.1`). The embedded server (`inapp/`, Objective-C) and the Python server
(`server/local_services.py`) implement the same API and store and are checked against each other by
`tests/test_parity.py`.

- Store: `Documents/LocalServices/` in the game's data (`store.json`, `ghosts/`, `avatars/`, `server.log`): never
  purged, included in device backups.
- Every start merges, best-only and without duplicates: the save's best times and the player's own ghosts, the
  opponent ghosts and avatars the game downloaded (`robot_ghost-*.robot`, `robot_image-*.robot`), and every save
  in `LocalServices/imports/<label>/` (`import_save.py --add`; the same profile counts as the player, another as a
  named rider).
- Names: opponents are known by a 32-bit hash of their profile id ("Rider 0D454E3E"). A register (`names` in the
  store) keeps the first real name any save, import or community bundle gives a hash, so it stays known.
- Results are kept best-only (fewer faults, then less time); the game uploads a ghost only for a new best, and the
  server keeps one ghost per player and leaderboard. The Hall of Fame (overall score sent after every race) keeps
  one entry per player; Donkey and crazy-bike runs have their own.
- Riders without a picture get a generated pixel-art helmet in their own colours (`server/avatars.py`).
- Requests with no local equivalent (gifts, PvP, weekly challenges, store targeting) are answered "nothing here".
- **Ports and copies.** macOS has one loopback for all apps, so each copy serves itself on its own port: 7979 for the
  original app, `7980 + sha256(bundle id) % 1000` for a `--bundle-id` copy, or `--port N` (written into the game's
  URLs and Info.plist `TFLocalServicesPort`); the installer warns if two installed copies share one. A server refuses
  logins from another app, and the game never switches accounts (`local-services-keep-account`): on a login with a
  different profile the original game parks the player's progress as `Documents/player_<hash>.prgstore` and starts a
  new player. Copies built before 2026-10-14 all use 7979 and keep running after their window closes: run one at a
  time and quit them with `pkill -x TrialsFrontier`.
- **Closing the window in PlayCover.** PlayCover's close button only hides an iOS app and removes its Dock icon; the
  in-app library then lets the game save and quits (only inside PlayCover; Cmd+H and minimising keep it running).

Development: build with `--server external`, then `python3 -I server/local_services.py` (logs every request; unknown
ones are marked `UNHANDLED`) and `python3 -I scripts/netwatch.py` (flags any non-loopback socket of the game).
`python3 -I scripts/build_inapp.py <dir>` builds `libTFLocalServices.dylib` and the macOS `tfserver`;
`python3 -I tests/test_parity.py <tfserver> <game Documents>` compares the two servers.

### Other tools

| path | what |
|---|---|
| `scripts/decode_save.py`, `extract_scores.py`, `list_ghosts.py`, `build_report.py` | save, best times, ghosts, a report with track names and medals |
| `scripts/import_save.py` | copy a save from a device or backup into the PlayCover game |
| `scripts/lbcache.py` | the game's friends leaderboard cache (`lbstorage.bin`): show, export |
| `scripts/level_audit.py` | which levels you have raced, own, or cannot reach any more |
| `scripts/unpack_datapack.py`, `datapack.py`, `level_info.py` | content packs, build-time content edits, level files |
| `scripts/make_keymap.py` | the PlayCover keymap (one virtual finger per thumb) |
| `scripts/extract_app_domain.py` | an app's files from an unencrypted iOS backup |
| `frida/`, `ghidra/scripts/`, `tools/ghidra-headless.sh` | runtime tracing and headless Ghidra helpers used during development |
| `docs/JOURNAL.md` | everything that was done, in order, and why |
| `docs/FORMATS.md`, `docs/BUNDLES.md`, `docs/MISSIONS.md`, `docs/EVENTS.md`, `docs/TODO.md` | file formats; the ghost-bundle format; adding missions; seasonal events; open items |

### Environment

- Python 3.12 (`.python-version`: pyenv-virtualenv `trials-frontier-patch-3.12`); `pip install -r requirements.txt`
  only for the Frida tools.
- Xcode (clang, iOS SDK) for the in-app server.
- Java 21 for Ghidra via SDKMAN (`.sdkmanrc`), only for analysis.
- Keep work files (game files, saves, builds) in a separate private folder, never in this repository.

## Legal

Trials Frontier was developed by RedLynx and published by Ubisoft; "Trials" and "Trials Frontier" are trademarks of
Ubisoft Entertainment. This is an unofficial fan project to preserve and keep playing a game whose online services
have ended, for people who own a copy. It is not affiliated with, endorsed, sponsored or supported by Ubisoft or
RedLynx, and all rights in the game (its code, artwork, levels, sounds and other content) remain theirs. If you hold
rights in the game and have concerns about this project, please open an issue.

**This repository contains no game files.** You need a copy of the game, preferably your own (see
[Getting the game files](#getting-the-game-files)). A raw save holds account ids and other players' names, so a
ghost bundle carries only times and ghosts, never the save itself.

MIT (see `LICENSE`) for this repository's own code, documentation and artwork (the generated helmet avatars).
Trials Frontier and its files belong to Ubisoft/RedLynx and are not part of this repository or covered by this
licence; the patch spec only quotes the few original bytes each patch replaces (under 1 KB in total: machine code
and a few URL strings), so that inputs and builds can be verified, and the sizes and checksums of the reference
app's content packs. The screenshot (`docs/images/`) shows the game's artwork, © Ubisoft/RedLynx.
Data you fetch with `community.py` keeps its own licences.
