"""Bring your old save (and ghosts) into the patched game in PlayCover.

Usage: python3 -I import_save.py <Documents folder from your device or backup> [--bundle-id <id>] [--yes]

<Documents folder>: the game's Documents as copied off your iPhone/iPad (scripts/extract_app_domain.py writes it
from an unencrypted backup): player.bin, ghost_*.bin, robot_*.robot, ...
--bundle-id: the copy to import into (build.py --bundle-id); default the original com.ubisoft.redlynx.trialsfrontier.

Start the patched game once and quit it first (PlayCover creates its data folder on the first start). Then this:
  1. refuses while the game runs;
  2. checks the save (name, best times) before touching anything;
  3. moves the copy's current Documents aside to <container>/Data/Documents-before-import-<time> (nothing is deleted);
  4. copies the files from your Documents folder (not its LocalServices: the local server's store starts fresh, so
     its next start imports your best times, your ghosts and the opponents the game had downloaded).
"""
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from local_services import decode, read_scores  # noqa: E402


def opt(name, flag=False):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = True if flag else sys.argv[i + 1]
        del sys.argv[i:i + (1 if flag else 2)]
        return val
    return None


def main():
    bundle_id = opt("--bundle-id") or "com.ubisoft.redlynx.trialsfrontier"
    yes = opt("--yes", True)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    src = os.path.abspath(os.path.expanduser(sys.argv[1]))
    data = os.path.expanduser(f"~/Library/Containers/{bundle_id}/Data")
    docs = os.path.join(data, "Documents")

    if subprocess.run(["pgrep", "-x", "TrialsFrontier"], capture_output=True).returncode == 0:
        sys.exit("the game is running: quit it first (close its window, or: pkill -x TrialsFrontier)")
    if not os.path.isdir(docs):
        sys.exit(f"{docs} not found: install the patched game, start it once and quit it, then run this again")
    save = os.path.join(src, "player.bin")
    if not os.path.isfile(save):
        sys.exit(f"{save} not found: give the game's Documents folder from your device or backup")
    try:
        raw = decode(open(save, "rb").read())[1]
    except Exception as e:  # noqa: BLE001 - any decoding problem means: not a usable save
        sys.exit(f"{save} is not a readable Trials Frontier save ({e})")
    name = raw[20:20 + 64].split(b"\0")[0].decode("utf-8", "replace") or "(no name yet)"
    files = [f for f in sorted(os.listdir(src)) if os.path.isfile(os.path.join(src, f)) and not f.startswith(".")]
    ghosts = [f for f in files if f.startswith("ghost_")]
    robots = [f for f in files if f.startswith("robot_")]
    print(f"save: rider {name}, {len(read_scores(raw))} best times; {len(ghosts)} ghost files, {len(robots)} opponent files"
          f"; {len(files)} files in all")
    print(f"into: {docs} (its current contents are moved aside first)")
    if not yes and input("import? [y/N] ").strip().lower() != "y":
        sys.exit("nothing changed")

    aside = os.path.join(data, "Documents-before-import-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.move(docs, aside)
    os.makedirs(docs)
    for f in files:
        shutil.copy2(os.path.join(src, f), os.path.join(docs, f))
    print(f"imported {len(files)} files; the previous contents are in {aside}")
    print("start the game: the local server imports your best times, ghosts and opponents on this first start")


if __name__ == "__main__":
    main()
