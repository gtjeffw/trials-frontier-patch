"""Install a patched Trials Frontier .ipa into PlayCover and set up the extras it needs on macOS.

Usage: python3 -I install_playcover.py <spec.json> <TrialsFrontier.app> [--ipa patched.ipa] [--keymap keymap.plist]
                                       [--dlc-from <folder with downloaded packs>] [--dry-run]

What it does (the game should be closed):
  1. --ipa: hand the .ipa to PlayCover (`open -a PlayCover`), which installs and re-signs it.
  2. Texture packs: every TrialsTexturesDL*.dat found anywhere in the user's .app that is NOT in the game's
     built-in texture-pack table (read from the executable at the spec's "pack_tables" address) is copied to the
     app container's Library/Caches/DLC, the only other place the game loads texture packs from
     (tr::GlobalData::findFilePacks). Nothing is hard-coded to one copy of the game.
  3. --dlc-from: packs the user saved from a device's Library/Caches/DLC (or elsewhere) are copied too, if the game
     can load them from there: TrialsTexturesDL*.dat and the fixed names in the spec's "dlc_content_names".
  4. Content packs (TrialsContent*.dat) in the bundle that are in neither the content table nor dlc_content_names
     cannot be loaded by this build; they are reported, not copied.
  5. --keymap: install the PlayCover keymap.
Re-run after the app's cache folder has been cleared.
"""
import json
import os
import shutil
import struct
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


def read_table(exe, vmaddr, count, prefix=""):
    """Read `count` C-string pointers at vmaddr (unslid, __TEXT based at 0x100000000)."""
    out = []
    for i in range(count):
        ptr = struct.unpack_from("<Q", exe, vmaddr - 0x100000000 + 8 * i)[0] & 0xFFFFFFFFFF
        end = exe.index(b"\0", ptr - 0x100000000)
        out.append(prefix + exe[ptr - 0x100000000:end].decode())
    return out


def is_texture_pack(path):
    with open(path, "rb") as f:
        head = f.read(12)
    if len(head) < 12:
        return False
    zero, count, entry = struct.unpack("<3I", head)
    return zero == 0 and entry == 24 and 0 < count < 100000


ipa, keymap, dlc_from, dry = opt("--ipa"), opt("--keymap"), opt("--dlc-from"), opt("--dry-run", True)
spec_path, app_dir = sys.argv[1:3]
spec = json.load(open(spec_path))
exe = open(os.path.join(app_dir, spec["executable"]), "rb").read()
tables = spec["pack_tables"]
tex_table = set(read_table(exe, int(tables["texture"]["vmaddr"], 16), tables["texture"]["count"], "TrialsTexturesDL"))
content_table = set(read_table(exe, int(tables["content"]["vmaddr"], 16), tables["content"]["count"]))
dlc_content = set(spec.get("dlc_content_names", []))

copies, report = [], []
for root, _, files in os.walk(app_dir):
    for name in sorted(files):
        path = os.path.join(root, name)
        if name.startswith("TrialsTexturesDL") and name.endswith(".dat") and name not in tex_table:
            if not is_texture_pack(path):
                report.append(f"skipped {path}: not a texture pack")
            elif name not in {os.path.basename(c[1]) for c in copies}:
                copies.append((path, name, "bundled texture pack missing from the game's table"))
        elif name.startswith("TrialsContent") and name.endswith(".dat") and name not in content_table:
            report.append(f"cannot load {os.path.relpath(path, app_dir)}: content pack not in this build's table")

if dlc_from:
    for name in sorted(os.listdir(dlc_from)):
        path = os.path.join(dlc_from, name)
        if name.startswith("TrialsTexturesDL") and name.endswith(".dat") and is_texture_pack(path):
            copies = [c for c in copies if c[1] != name] + [(path, name, "user-supplied downloaded texture pack")]
        elif name in dlc_content:
            copies.append((path, name, "user-supplied downloaded content pack"))
        elif name.endswith(".dat"):
            report.append(f"ignored {path}: the game does not load this name from the download folder")

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
