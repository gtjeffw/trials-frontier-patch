"""Which packs the game can only load from its download folder (__getSaveFilePath type 6, "DLC").

The game loads texture packs from a fixed 21-name table (spec "pack_tables") and content packs from a 12-name table;
anything else is only found in the download folder: every TrialsTexturesDL*.dat there, and content packs under three
fixed names (spec "dlc_content_names"). With the compat patch dlc-folder-in-bundle that folder is the app's own DLC/
(scripts/build_ipa.py fills it); without it, Library/Caches/DLC in the app's data (scripts/install_playcover.py).

plan(spec, app_dir, dlc_from=None) -> (copies, notes): copies = [(source path, name in DLC/, reason)]
  - bundled TrialsTexturesDL*.dat not in the texture table (header-checked);
  - packs the player saved from a device's download folder (--dlc-from): texture packs and the fixed content names;
  - bundled TrialsContent*.dat in neither table under a free name from "dlc_content_alias_slots" (names whose real
    downloaded packs are lost), unless the player supplied a real pack for that name.
"""
import os
import struct


def read_table(exe, vmaddr, count, prefix=""):
    """`count` C-string pointers at vmaddr (unslid, __TEXT based at 0x100000000)."""
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


def plan(spec, app_dir, dlc_from=None, exe_path=None):
    exe = open(exe_path or os.path.join(app_dir, spec["executable"]), "rb").read()
    tables = spec["pack_tables"]
    tex_table = set(read_table(exe, int(tables["texture"]["vmaddr"], 16), tables["texture"]["count"], "TrialsTexturesDL"))
    content_table = set(read_table(exe, int(tables["content"]["vmaddr"], 16), tables["content"]["count"]))
    dlc_content = set(spec.get("dlc_content_names", []))
    copies, notes, unloadable = [], [], []
    for root, dirs, files in os.walk(app_dir):
        dirs[:] = sorted(d for d in dirs if d != "DLC")
        for name in sorted(files):
            path = os.path.join(root, name)
            if name.startswith("TrialsTexturesDL") and name.endswith(".dat") and name not in tex_table:
                if not is_texture_pack(path):
                    notes.append(f"skipped {path}: not a texture pack")
                elif name not in {c[1] for c in copies}:
                    copies.append((path, name, "bundled texture pack missing from the game's table"))
            elif (name.startswith("TrialsContent") and name.endswith(".dat") and name not in content_table
                  and name not in dlc_content and name not in {u[1] for u in unloadable}):
                unloadable.append((path, name))
    if dlc_from:
        for name in sorted(os.listdir(dlc_from)):
            path = os.path.join(dlc_from, name)
            if name.startswith("TrialsTexturesDL") and name.endswith(".dat") and is_texture_pack(path):
                copies = [c for c in copies if c[1] != name] + [(path, name, "player's downloaded texture pack")]
            elif name in dlc_content:
                copies.append((path, name, "player's downloaded content pack"))
            elif name.endswith(".dat"):
                notes.append(f"ignored {path}: the game does not load this name from the download folder")
    taken = {c[1] for c in copies}
    free = [n for n in spec.get("dlc_content_alias_slots", []) if n not in taken]
    for path, name in unloadable:
        if free:
            slot = free.pop(0)
            copies.append((path, slot, f"{name} is not in the game's content table; under a lost download name"))
        else:
            notes.append(f"cannot load {os.path.relpath(path, app_dir)}: not in the content table and no free slot")
    return copies, notes
