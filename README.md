# trials-frontier-patch

Trials Frontier is an excellent game in the Trials series by Ubisoft RedLynx. Unfortunately, it is no longer
available. Even if you got this free-to-play game while it was still being distributed and supported, you can no
longer play it, because Ubisoft shut down its servers.

This project lets you ride again. Starting from *your own* copy of **Trials Frontier 7.9.0** for iOS, it builds
a patched app that:

- runs on an Apple-silicon Mac in [PlayCover](https://playcover.io) with keyboard controls, or sideloaded on an
  iPhone/iPad with a free Apple ID;
- recovers your old save, provided it is still on your iPhone/iPad (or in a backup of it). Unfortunately you will
  likely find ghosts for only some of your best times: the save keeps every time, but the game kept ghosts only
  as separate local files, and not for every run;
- keeps the game's data safe on iPhone/iPad: content packs the game would only load from its cache folder ship inside
  the app, so iOS can't clean them up, and with the `file-sharing` option the save and ghosts show up in Finder and
  the Files app for easy copying and editing;
- works fully offline, with ads, tracking and every connection to Ubisoft/RedLynx switched off;
- replaces Ubisoft's shut-down servers with an internal server, so leaderboards and ghost races work again;
- races other riders: your downloaded opponents, other players' published ghost bundles, and optionally the 2019
  world records; new players get a working game too;
- optionally: buy coins with gems, open every level that can no longer be unlocked, and more (see *Options*).

You can also share your own runs with other players as a ghost bundle.

**This repository contains no game files.** You need your own copy of the game, including an unencrypted copy of
its executable (see *Getting the game files*). A raw save holds account ids and other players' names, so a ghost
bundle carries only times and ghosts, never the save itself (see *Sharing your ghosts*).

**Disclaimer.** Trials Frontier was developed by RedLynx and published by Ubisoft; "Trials" and "Trials Frontier" are
trademarks of Ubisoft Entertainment. This is an unofficial fan project to preserve and keep playing a game whose
online services have ended, for people who own a copy. It is not affiliated with, endorsed, sponsored or supported
by Ubisoft or RedLynx, and all rights in the game (its code, artwork, levels, sounds and other content) remain
theirs. If you hold rights in the game and have concerns about this project, please open an issue.

## Quick start (PlayCover on an Apple-silicon Mac)

```
python3 -I build.py --app <TrialsFrontier.app> --work <work dir> --decrypted <unencrypted TrialsFrontier> --install --keymap
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
| `--bundle-id`, `--display-name` | a second copy next to the original with its own data (iPhone/iPad, or PlayCover: one at a time) |
| `--avatars <dir>` | `<profileId>.png` (146×146) pictures shown on the leaderboards, e.g. your own Ubisoft avatar |
| `--community [<layer>]` | build other riders into the app (see *Other riders*; for iPhone/iPad, where `community.py install` cannot reach the data) |

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
  server keeps one ghost per player and leaderboard. The Hall of Fame (overall score the game sends after every
  race) is one entry per player, replaced by each newer score.
- Riders without a picture (new players, world-record holders, most downloaded opponents) get a generated
  pixel-art helmet in their own colours (shape, colours and pattern from their id; `server/avatars.py`).
- Requests with no local equivalent (gifts, PvP, weekly challenges, store targeting) are answered "nothing here".

Development: build with `--server external`, then `python3 -I server/local_services.py` (logs every request; unknown
ones are marked `UNHANDLED`) and `python3 -I scripts/netwatch.py` (flags any non-loopback socket of the game).
`python3 -I scripts/build_inapp.py <dir>` builds `libTFLocalServices.dylib` and the macOS `tfserver`;
`python3 -I tests/test_parity.py <tfserver> <game Documents>` compares the two servers.

## Getting the game files

You need two things from **your own copy** of Trials Frontier 7.9.0 (arm64, as installed on a 64-bit iPhone or
iPad):

1. **The app bundle** `TrialsFrontier.app`: its content packs, artwork and settings. It can be copied from an
   unencrypted device backup (`scripts/extract_app_domain.py` handles the app's data; the bundle itself may need a
   device you can access directly).
2. **An unencrypted copy of its executable.** App Store apps are protected with Apple's FairPlay encryption on the
   device, so the executable inside the bundle cannot be patched as it is. There are well-established community
   methods to jailbreak an older iOS device and decrypt apps installed on it, for example an old iPhone or iPad
   that still has Trials Frontier installed. This project does not provide or link to such tools.

**Check your local laws and regulations first.** In many countries, circumventing copy protection is restricted
even for software you own (for example the US DMCA, section 1201, or the EU's Copyright Directive), with
exceptions that differ from country to country. Whether and how you obtain an unencrypted copy is your own
decision and responsibility.

`build.py --decrypted <executable>` checks what you give it before patching anything: the right build (Mach-O
UUID), not encrypted, the formerly encrypted code identical to the reference, and every patch site holding exactly
the original bytes. An executable that is byte-identical to the reference gives byte-identical, verified builds;
one from another tool that only differs in details such as its code signature is accepted too.

Packs from the game's download folder (`Library/Caches/DLC` on the device) can be added with
`scripts/install_playcover.py --dlc-from <folder>`; most of what they contained also ships in the app.

## Sharing your ghosts

`scripts/ghost_bundle.py` turns your best times and ghosts into a *bundle* and publishes it as a public GitHub
repository (`gh` login, the web login is fine; you confirm that the runs are yours; the files are committed through
GitHub's API, so GitHub signs every commit for your account: no key to keep). `ghost_bundle.py update` publishes your new best times later.
Bundles never contain your save, your profile id or game files. Format: `docs/BUNDLES.md`.

```
python3 -I scripts/ghost_bundle.py export <game Documents> <bundle dir> [--app <TrialsFrontier.app>] [--avatar <png>]
python3 -I scripts/ghost_bundle.py publish <bundle dir> --dry-run   # builds <bundle dir>-preview, publishes nothing
python3 -I scripts/ghost_bundle.py publish <bundle dir>
python3 -I scripts/ghost_bundle.py update <bundle dir> [--documents <iPhone/iPad Documents copy>]  # new best times
```

## Other riders

`scripts/community.py` brings other riders' bundles (and, optionally, the 2019 world records from
[dutscher/trialstrackmap](https://github.com/dutscher/trialstrackmap), MIT) into your game: a list of sources,
fetched and checked into a local cache, merged into a *community layer* the local server reads. Your own results
are never changed by it, and running `update` again picks up new and revised bundles.

Each source keeps its own licence (bundles: chosen by their publishers; the world records: MIT). Playing with them
is fine; if you republish the data, pass on a layer or an app with one built in, or serve it publicly, check and
honour every source's licence: `community.py build` prints them and writes `NOTICE.md` into the layer
(`docs/BUNDLES.md`, *Licences*).

```
python3 -I scripts/community.py enable world-records-2019      # optional
python3 -I scripts/community.py add <owner>/<repo>             # any published bundle; `discover` lists them
python3 -I scripts/community.py update                         # fetch, check, build, install (game closed)
```

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
| `docs/FORMATS.md`, `docs/BUNDLES.md`, `docs/TODO.md` | file formats; the ghost-bundle format; open items |

## Environment

- Python 3.12 (`.python-version`: pyenv-virtualenv `trials-frontier-patch-3.12`); `pip install -r requirements.txt`
  only for the Frida tools.
- Xcode (clang, iOS SDK) for the in-app server.
- Java 21 for Ghidra via SDKMAN (`.sdkmanrc`), only for analysis.
- Keep work files (game files, saves, builds) in a separate private folder, never in this repository.

## Status

Tested with PlayCover on macOS and sideloaded on an iPhone 15 Pro (iOS 26) and an iPad Air 2 (iOS 15): the whole game
plays offline with keyboard controls, for a restored profile and for a brand-new player (tutorial, naming, story);
leaderboards and the Hall of Fame with your own results, downloaded opponents, published bundles and optional world
records; racing and uploading ghosts; A.N.B.A.'s live opponents; avatars (generated helmets for riders without one);
coins for gems; hidden, orphan and developer levels. Publishing a bundle and fetching it from GitHub work end to
end. Open items (PvP duels, top five on FRIENDS, event tracks, native keyboard/controller input, a guide for players
without a jailbreak) are in `docs/TODO.md`.

## Licence

MIT (see `LICENSE`) for this repository's own code, documentation and artwork (the generated helmet avatars).
Trials Frontier and its files belong to Ubisoft/RedLynx and are not part of this repository or covered by this
licence; the patch spec only quotes the few original bytes each patch replaces (about 1.5 KB of machine code in
total), so that inputs and builds can be verified. Data you fetch with `community.py` keeps its own licences.
