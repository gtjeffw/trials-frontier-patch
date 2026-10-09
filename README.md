# trials-frontier-patch

Tools and notes for preserving and running **Trials Frontier 7.9.0** (RedLynx/Ubisoft, iOS) after its
online services ended: decode your own save, ghosts and best times; build a patched copy of *your own*
installed game that runs on an Apple-silicon Mac via PlayCover.

This repository contains **no game files**. You need your own installed copy of the game (and a way to read
its one encrypted page, see below). Do not publish decrypted game files, game assets, or save files (saves
contain account ids and other players' names).

## Layout

| path | what |
|---|---|
| `patches/trials-frontier-7.9.0.json` | binary patches as data: address, original bytes, new bytes, reason, plus sha256 of every stage |
| `scripts/apply_patches.py` | apply the spec to the decrypted executable (or encrypted executable + `--page`) |
| `scripts/build_ipa.py` | reproducible `.ipa` from the original `.app` + patched executable |
| `a private helper` | read the FairPlay-encrypted page from memory via Frida (jailbroken device) |
| `scripts/decode_save.py`, `extract_scores.py`, `list_ghosts.py` | save / score / ghost decoding |
| `scripts/unpack_datapack.py`, `build_report.py` | content packs, track names, medals, combined report |
| `scripts/extract_app_domain.py` | pull an app's files out of an unencrypted iOS backup |
| `frida/` | runtime tracing scripts used during development |
| `ghidra/scripts/` | headless Ghidra helpers (`Decompile.java`, `Refs.java`) |
| `tools/ghidra-headless.sh` | runs Ghidra with the JDK pinned in `.sdkmanrc` |
| `docs/JOURNAL.md` | what was done, in order, and why |
| `docs/FORMATS.md` | file formats and the code they were derived from |

## Environment

- Python 3.12 (pyenv-virtualenv `trials-frontier-patch-3.12`, see `.python-version`), `pip install -r requirements.txt`.
- Java 21 for Ghidra via SDKMAN (`.sdkmanrc`).
- Work files go in a separate private workspace, never in this repository.

## Build (outline)

```
python3 -I scripts/apply_patches.py patches/trials-frontier-7.9.0.json \
    <TrialsFrontier.app>/TrialsFrontier <work>/TrialsFrontier.patched --page <work>/page.bin
python3 -I scripts/build_ipa.py <TrialsFrontier.app> <work>/TrialsFrontier.patched <work>/TrialsFrontier-patched.ipa \
    --spec patches/trials-frontier-7.9.0.json
```

Each step verifies sha256 values from the spec, so the same inputs always give the same output.

Patches are grouped: `compat` (needed to run on macOS/PlayCover without the dead content bucket), `privacy`
(ads, cross-promotion), `offline` (no Ubisoft/RedLynx services). `--groups compat,privacy` builds without the
offline group, e.g. for a future fan server.

Keyboard controls: install `playcover/trials-frontier-keymap.plist` as
`~/Library/Containers/io.playcover.PlayCover/Keymapping/com.ubisoft.redlynx.trialsfrontier.plist` and enable
Keymapping for the app. PlayCover needs a custom resolution of 1366×1024 for now.

## Status

Runs in PlayCover through the tutorial with a 1366×1024 custom window. Known issues and progress are in
`docs/JOURNAL.md`.
