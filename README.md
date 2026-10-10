# trials-frontier-patch

Tools and notes for preserving and playing **Trials Frontier 7.9.0** (RedLynx/Ubisoft, iOS) after its online
services ended. From *your own* copy of the game you can build a patched app that:

- runs on an Apple-silicon Mac in [PlayCover](https://playcover.io) (iPhone/iPad sideloading is planned), with keyboard
  controls;
- works fully offline, with ads, tracking and every connection to Ubisoft/RedLynx switched off;
- serves its own leaderboards, ghosts and login from inside the app on `127.0.0.1` — race your own ghosts, upload new
  best runs, see the opponents the game downloaded over the years;
- optionally: buy coins with gems, open every level that can no longer be unlocked, and more (see *Options*).

It also decodes your save, best times and ghosts.

**This repository contains no game files.** You need your own installed copy of the game, and for an encrypted
copy a way to read its one encrypted page (see *Getting the game files*). Do not publish decrypted game files, game
assets or saves (saves contain account ids and other players' names).

## Quick start (PlayCover on an Apple-silicon Mac)

```
python3 -I build.py --app <TrialsFrontier.app> --work <work dir> --decrypted <decrypted TrialsFrontier> --install --keymap
```

`build.py` patches the executable, builds the in-app server (needs Xcode), packages a reproducible `.ipa` (with the
packs the game only loads from its download folder placed inside the app) and hands it to PlayCover. Close the game first. Then in
PlayCover set **Resolution: Custom** to your screen's size in points with scaling 2 (e.g. 1512×982 on a 14" MacBook
Pro, 1920×1080 on a 1080p monitor) and enable **Keymapping**; full screen (green button) then fills the display.

The patched app keeps your progress across rebuilds: PlayCover only replaces the app, not its data. To quit the game
completely (Cmd+Q in PlayCover only hides it): `pkill -x TrialsFrontier`.

## iPhone / iPad (sideloading with a free Apple ID)

```
python3 -I build.py --app <TrialsFrontier.app> --work <work> --decrypted <executable> \
    --with file-sharing --bundle-id com.<you>.trialsfrontier --display-name "Trials Offline"
python3 -I scripts/sign_ios.py <work>/TrialsFrontier-7.9.0-patched.ipa <work>/signed
python3 -I scripts/ios_device.py install <device> <work>/signed/TrialsFrontier.app      # iOS 17+
ideviceinstaller -u <udid> install <work>/signed/TrialsFrontier-7.9.0-patched-signed.ipa # older iOS
```

Once: sign in to Xcode with your Apple ID, create any iOS app with the same bundle id and your Personal Team, and run
it on each device (this registers the device and creates the certificate and profile). The app installs next to the
original. Your data: `scripts/ios_device.py push-data` (iOS 17+) or drag the files in with Finder (file sharing).
Free signatures last 7 days: re-run `sign_ios.py` and reinstall; the game's data stays. If there is no sound, check
the silent switch.

## Options

| `build.py` | what |
|---|---|
| `--server embedded` (default) | the game serves leaderboards, ghosts and login itself (`local-services` + `embedded-server`) |
| `--server external` | same game, but you run the server: `server/local_services.py` (Python) or `tfserver` — for development |
| `--server none` | no local services; every online feature stays off |
| `--with coins-for-gems` | coin packs (App Store only) become gem-priced shop items, priced like the gem pack of the same tier |
| `--with open-all-levels` | the game's own developer switch reveals every level on the map (event, X-Games, Bunker tracks …) |
| `--with orphan-levels` | gives the six levels without a map position a place in the main map's fogged east (PvP tracks keep "any bike") |
| `--with dev-levels` | names and places six unfinished developer test levels that ship with the game |
| `--with file-sharing` | shows the game's data (save, ghosts, server store) in Finder and the Files app — for iPhone/iPad |
| `--bundle-id`, `--display-name` | install next to the original app (iPhone/iPad) |
| `--avatars <dir>` | `<profileId>.png` (146×146) pictures shown on the leaderboards, e.g. your own Ubisoft avatar |
| `--world-records` + `--world-record-ids` | add the 2019 world records from [dutscher/trialstrackmap](https://github.com/dutscher/trialstrackmap) (MIT; `database/wr/wrrider.json` and `database/trackdata/ids.json`, downloaded by you) |

The always-on patch groups are `compat` (runs outside a team-signed install, without the dead content bucket),
`privacy` (ads, cross-promotion, analytics SDKs off), `offline` (no Ubisoft/RedLynx services; the online code itself is
kept, so a fan server could replace this group) and `economy` (no fuel use, unlimited gems; coins unchanged). Every
patch is data in `patches/trials-frontier-7.9.0.json`: address, original and new bytes, and the reason.

## Local services

With `local-services` the game logs in silently, fetches its configuration and talks to a game server — all on
`127.0.0.1:7979`; the app may not reach any other host (the HTTP layer only allows `http://127.0.0.1:` URLs and
`getaddrinfo` only resolves `127.0.0.1`). The embedded server (`inapp/`, Objective-C) and the Python server
(`server/local_services.py`) implement the same API and store and are checked against each other by
`tests/test_parity.py`.

- Store: `Documents/LocalServices/` in the game's data (`store.json`, `ghosts/`, `avatars/`, `server.log`) — never
  purged, included in device backups. On PlayCover: `~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/`.
- First start imports your best times and ghosts from the save, and the opponent ghosts and avatars the game had
  downloaded (`robot_ghost-*.robot`, `robot_image-*.robot`).
- Results are kept best-only (fewer faults, then less time); the game uploads a ghost only for a new best, and the
  server keeps one ghost per player and leaderboard.
- Requests with no local equivalent (gifts, PvP, weekly challenges, store targeting) are answered "nothing here".

Development: build with `--server external`, then `python3 -I server/local_services.py` (logs every request; unknown
ones are marked `UNHANDLED`) and `python3 -I scripts/netwatch.py` (flags any non-loopback socket of the game).
`python3 -I scripts/build_inapp.py <dir>` builds `libTFLocalServices.dylib` and the macOS `tfserver`;
`python3 -I tests/test_parity.py <tfserver> <game Documents>` compares the two servers.

## Getting the game files

You need the `TrialsFrontier.app` of version 7.9.0 (e.g. from a device backup or a jailbroken device) and its
executable without FairPlay encryption. An unencrypted copy of your own executable is needed (`--decrypted`). Every input is checked against the sha256 values in the patch spec.

Packs from the game's download folder (`Library/Caches/DLC` on the device) can be added with
`scripts/install_playcover.py --dlc-from <folder>`; most of what they contained also ships in the app.

## Other tools

| path | what |
|---|---|
| `scripts/decode_save.py`, `extract_scores.py`, `list_ghosts.py`, `build_report.py` | save, best times, ghosts, a report with track names and medals |
| `scripts/level_audit.py` | which levels you have raced, own, or cannot reach any more |
| `scripts/unpack_datapack.py`, `datapack.py`, `level_info.py` | content packs, build-time content edits, level files |
| `scripts/make_keymap.py` | the PlayCover keymap (one virtual finger per thumb) |
| `scripts/extract_app_domain.py` | an app's files from an unencrypted iOS backup |
| `frida/`, `ghidra/scripts/`, `tools/ghidra-headless.sh` | runtime tracing and headless Ghidra helpers used during development |
| `docs/JOURNAL.md` | everything that was done, in order, and why |
| `docs/FORMATS.md`, `docs/TODO.md` | file formats; open items |

## Environment

- Python 3.12 (`.python-version`: pyenv-virtualenv `trials-frontier-patch-3.12`); `pip install -r requirements.txt`
  only for the Frida tools.
- Xcode (clang, iOS SDK) for the in-app server.
- Java 21 for Ghidra via SDKMAN (`.sdkmanrc`), only for analysis.
- Keep work files (game files, saves, builds) in a separate private folder, never in this repository.

## Status

Tested with PlayCover on macOS and sideloaded on an iPhone 15 Pro (iOS 26) and an iPad Air 2 (iOS 15): the whole game plays offline with keyboard controls; leaderboards with your own
results, downloaded opponents and optional world records; racing and uploading ghosts; avatars; coins for gems;
hidden, orphan and developer levels reachable. Open items (a robot-challenge module, top five on
FRIENDS, native keyboard/controller input) are in `docs/TODO.md`.
