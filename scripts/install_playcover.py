"""Install a patched Trials Frontier .ipa into PlayCover.

Usage: python3 -I install_playcover.py <spec.json> <TrialsFrontier.app> [--ipa patched.ipa] [--keymap keymap.plist]
                                       [--caches-dlc [--dlc-from <folder>]] [--dry-run]

  --ipa:        hand the .ipa to PlayCover (`open -a PlayCover`), which installs and re-signs it (game closed).
  --keymap:     install the PlayCover keymap (enable Keymapping for the app in PlayCover).
  --caches-dlc: only for builds without the compat patch dlc-folder-in-bundle: copy the packs the game can only load
                from its download folder (scripts/dlcpacks.py) into the app data's Library/Caches/DLC. Current builds
                carry them inside the app (build_ipa.py puts them into TrialsFrontier.app/DLC).
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


def opt(name, flag=False):
    if name in sys.argv:
        i = sys.argv.index(name)
        if flag:
            del sys.argv[i]
            return True
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return False if flag else None


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dlcpacks  # noqa: E402

ipa, keymap, dlc_from = opt("--ipa"), opt("--keymap"), opt("--dlc-from")
caches, dry = opt("--caches-dlc", True), opt("--dry-run", True)
spec_path, app_dir = sys.argv[1:3]
spec = json.load(open(spec_path))
copies, report = dlcpacks.plan(spec, app_dir, dlc_from) if caches else ([], [])

if ipa:
    print(f"install {ipa} via PlayCover")
    if not dry:
        subprocess.run(["open", "-a", "PlayCover", ipa], check=True)

dlc = os.path.join(CONTAINER, "Library/Caches/DLC")
if copies and not dry and not os.path.isdir(CONTAINER):
    sys.exit(f"{CONTAINER} not found: launch the game once in PlayCover first, then re-run")
for src, name, why in copies:
    print(f"copy {name} -> Library/Caches/DLC ({why})")
    if not dry:
        os.makedirs(dlc, exist_ok=True)
        shutil.copy2(src, os.path.join(dlc, name))
for line in report:
    print("note:", line)

if keymap:
    dst = os.path.join(PLAYCOVER, "Keymapping", BUNDLE_ID + ".plist")
    print(f"install keymap -> {dst} (enable Keymapping for the app in PlayCover)")
    if not dry:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(keymap, dst)
