"""Install a patched Trials Frontier .ipa into PlayCover.

Usage: python3 -I install_playcover.py <spec.json> <TrialsFrontier.app> [--ipa patched.ipa] [--keymap keymap.plist]
                                       [--bundle-id <id>] [--port N] [--caches-dlc [--dlc-from <folder>]] [--dry-run]

  --ipa:        hand the .ipa to PlayCover (`open -a PlayCover`), which installs and re-signs it (game closed).
  --keymap:     install the PlayCover keymap (enable Keymapping for the app in PlayCover).
  --bundle-id:  the bundle id the .ipa was built with (build.py --bundle-id), for a second copy of the game with its
                own data; default com.ubisoft.redlynx.trialsfrontier.
  --port:       the local services port the build uses (build.py --port): warns if another installed copy of the game
                uses the same one (copies built before per-copy ports all use 7979).
  --caches-dlc: only for builds without the compat patch dlc-folder-in-bundle: copy the packs the game can only load
                from its download folder (scripts/dlcpacks.py) into the app data's Library/Caches/DLC. Current builds
                carry them inside the app (build_ipa.py puts them into TrialsFrontier.app/DLC).
"""
import json
import plistlib
import os
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
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
BUNDLE_ID = opt("--bundle-id") or "com.ubisoft.redlynx.trialsfrontier"
PORT = opt("--port")
CONTAINER = os.path.join(HOME, "Library/Containers", BUNDLE_ID, "Data")
spec_path, app_dir = sys.argv[1:3]
spec = json.load(open(spec_path))
copies, report = dlcpacks.plan(spec, app_dir, dlc_from) if caches else ([], [])

if PORT:
    apps = os.path.join(PLAYCOVER, "Applications")
    for name in sorted(os.listdir(apps)) if os.path.isdir(apps) else []:
        try:
            info = plistlib.load(open(os.path.join(apps, name, "Info.plist"), "rb"))
        except (OSError, plistlib.InvalidFileException):
            continue
        other = info.get("CFBundleIdentifier")
        if info.get("CFBundleExecutable") != spec["executable"] or other == BUNDLE_ID:
            continue
        if not os.path.exists(os.path.join(apps, name, "Frameworks", "libTFLocalServices.dylib")):
            continue  # no embedded local services (original game, or an external-server build)
        theirs = int(info.get("TFLocalServicesPort", 7979))
        if theirs == int(PORT):
            print(f"WARNING: {other} also serves on port {theirs}; never run the two at the same time, or rebuild one "
                  "with another --port")
        else:
            print(f"ok: {other} uses port {theirs}")

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
