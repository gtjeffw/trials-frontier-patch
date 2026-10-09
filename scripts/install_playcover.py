"""Install a patched Trials Frontier .ipa into PlayCover and set up the extras it needs on macOS.

Usage: python3 -I install_playcover.py <spec.json> <TrialsFrontier.app from device> [--ipa patched.ipa] [--keymap keymap.plist]

Steps (each optional input is skipped if not given):
  1. --ipa: hand the .ipa to PlayCover (`open -a PlayCover`), which installs/re-signs it.
  2. Copy the bundled texture packs listed in the spec's "dlc_folder_packs" into the app container's
     Library/Caches/DLC. The game's built-in texture-pack table (21 names) predates these packs; it only finds them
     in the download folder, which is empty without Ubisoft's servers. Re-run after the cache is cleared.
  3. --keymap: install the PlayCover keymap.
The game should be closed while this runs.
"""
import json
import os
import shutil
import subprocess
import sys

BUNDLE_ID = "com.ubisoft.redlynx.trialsfrontier"
HOME = os.path.expanduser("~")
CONTAINER = os.path.join(HOME, "Library/Containers", BUNDLE_ID, "Data")
PLAYCOVER = os.path.join(HOME, "Library/Containers/io.playcover.PlayCover")


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


ipa, keymap = opt("--ipa"), opt("--keymap")
spec_path, app_dir = sys.argv[1:3]
spec = json.load(open(spec_path))

if ipa:
    subprocess.run(["open", "-a", "PlayCover", ipa], check=True)
    print(f"handed {ipa} to PlayCover")

packs = spec.get("dlc_folder_packs", [])
if packs:
    if not os.path.isdir(CONTAINER):
        sys.exit(f"{CONTAINER} not found: launch the game once in PlayCover first, then re-run")
    dlc = os.path.join(CONTAINER, "Library/Caches/DLC")
    os.makedirs(dlc, exist_ok=True)
    for entry in packs:
        src = os.path.join(app_dir, entry["source"])
        dst = os.path.join(dlc, os.path.basename(entry["source"]))
        shutil.copy2(src, dst)
        print(f"copied {entry['source']} -> {dst}")

if keymap:
    dst = os.path.join(PLAYCOVER, "Keymapping", BUNDLE_ID + ".plist")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(keymap, dst)
    print(f"installed keymap -> {dst} (enable Keymapping for the app in PlayCover)")
