"""Install the signed game on a connected iPhone/iPad and move its data, with Xcode's devicectl.

Usage:
  python3 -I ios_device.py devices
  python3 -I ios_device.py install   <device> <signed TrialsFrontier.app>
  python3 -I ios_device.py push-data <device> <bundle id> [<Documents dir>]   copy save, ghosts, opponents, store
  python3 -I ios_device.py pull-data <device> <bundle id> <backup dir>          copy the device's Documents to the Mac
  python3 -I ios_device.py list      <device> <bundle id>

<device> is a name, UDID or identifier from `devices`. <Documents dir> defaults to the PlayCover copy
(~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Documents). push-data copies player.bin, ghost_*.bin,
robot_*.robot and LocalServices/ (the server store); close the game on the device first, or it will save over them.
Works for development-signed installs (scripts/sign_ios.py).
"""
import os
import subprocess
import sys

PLAYCOVER_DOCS = os.path.expanduser("~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data/Documents")


def devicectl(*args, check=True):
    cmd = ["xcrun", "devicectl"] + list(args)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"devicectl {' '.join(args[:3])} failed:\n{r.stderr or r.stdout}")
    return r.stdout


def wanted(rel):
    name = os.path.basename(rel)
    return (rel == "player.bin" or rel.startswith("LocalServices/") or
            (name.startswith("ghost_") and name.endswith(".bin")) or
            (name.startswith("robot_") and name.endswith(".robot")) or name.startswith("friend-"))


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "devices":
        print(devicectl("list", "devices"))
    elif cmd == "install":
        device, app = sys.argv[2:4]
        print(devicectl("device", "install", "app", "--device", device, app))
    elif cmd == "list":
        device, bundle = sys.argv[2:4]
        print(devicectl("device", "info", "files", "--device", device, "--domain-type", "appDataContainer",
                        "--domain-identifier", bundle, "--subdirectory", "Documents"))
    elif cmd == "push-data":
        device, bundle = sys.argv[2:4]
        docs = sys.argv[4] if len(sys.argv) > 4 else PLAYCOVER_DOCS
        files = []
        for root, _, names in os.walk(docs):
            for n in sorted(names):
                rel = os.path.relpath(os.path.join(root, n), docs)
                if wanted(rel) and not rel.endswith("server.log"):
                    files.append(rel)
        print(f"copying {len(files)} files from {docs} to {bundle} on {device}")
        for i, rel in enumerate(files, 1):
            devicectl("device", "copy", "to", "--device", device, "--domain-type", "appDataContainer",
                      "--domain-identifier", bundle, "--source", os.path.join(docs, rel), "--destination", "Documents/" + rel)
            if i % 50 == 0 or i == len(files):
                print(f"  {i}/{len(files)}")
    elif cmd == "pull-data":
        device, bundle, dest = sys.argv[2:5]
        os.makedirs(dest, exist_ok=True)
        print(devicectl("device", "copy", "from", "--device", device, "--domain-type", "appDataContainer",
                        "--domain-identifier", bundle, "--source", "Documents", "--destination", dest))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
