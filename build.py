"""Build (and optionally install) a patched Trials Frontier 7.9.0 from your own copy of the app.

Usage:
  python3 -I build.py --app <TrialsFrontier.app> --work <work dir>
                      [--page <page.bin> | --decrypted <decrypted TrialsFrontier executable>]
                      [--server embedded|external|none] [--with group,group,...]
                      [--avatars <dir>] [--world-records wrrider.json --world-record-ids ids.json]
                      [--install] [--keymap] [--dry-run]

Steps (each verified against the sha256 values in patches/trials-frontier-7.9.0.json where they exist):
  1. executable: the app's own if it is not encrypted (cryptid 0), else --decrypted, else the encrypted one plus the
     page read by a private helper (--page);
  2. scripts/apply_patches.py: the default groups (compat, privacy, offline, economy) plus the chosen options;
  3. with --server embedded: scripts/build_inapp.py builds libTFLocalServices.dylib (needs Xcode);
  4. scripts/build_ipa.py: a reproducible .ipa in --work;
  5. with --install: scripts/install_playcover.py hands it to PlayCover and copies the texture packs the game only
     loads from Library/Caches/DLC (and the keyboard map with --keymap). Close the game first.

--server:   embedded (default) = the game serves leaderboards, ghosts and login itself on 127.0.0.1:7979
                                 (local-services + embedded-server);
            external = local-services only; run server/local_services.py (or tfserver) yourself, e.g. for development;
            none     = no local services (everything online stays off).
--with:     optional extras: coins-for-gems, open-all-levels, orphan-levels, dev-levels (see README).
"""
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "patches", "trials-frontier-7.9.0.json")
PY = [sys.executable, "-I"]


def opt(name, flag=False, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if flag:
            del sys.argv[i]
            return True
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return False if flag else default


def cryptid(path):
    data = open(path, "rb").read(65536)
    _, _, _, _, ncmds = struct.unpack_from("<5I", data, 0)
    off = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<2I", data, off)
        if cmd == 0x2C:  # LC_ENCRYPTION_INFO_64
            return struct.unpack_from("<I", data, off + 16)[0]
        off += size
    return 0


def run(cmd, dry):
    print("+ " + " ".join(cmd))
    if not dry:
        subprocess.run(cmd, check=True)


def main():
    app, work = opt("--app"), opt("--work")
    page, decrypted = opt("--page"), opt("--decrypted")
    server = opt("--server", default="embedded")
    extra = [g for g in (opt("--with", default="") or "").split(",") if g]
    avatars, wr, wr_ids = opt("--avatars"), opt("--world-records"), opt("--world-record-ids")
    install, keymap, dry = opt("--install", True), opt("--keymap", True), opt("--dry-run", True)
    if not app or not work or server not in ("embedded", "external", "none") or len(sys.argv) > 1:
        sys.exit(__doc__)
    spec = json.load(open(SPEC))
    optional = set(spec["optional_groups"])
    groups = {"embedded": ["local-services", "embedded-server"], "external": ["local-services"], "none": []}[server] + extra
    unknown = [g for g in extra if g not in optional or g in ("local-services", "embedded-server")]
    if unknown:
        sys.exit(f"unknown option(s) for --with: {', '.join(unknown)} (choose from "
                 f"{', '.join(sorted(optional - {'local-services', 'embedded-server'}))})")
    exe_groups = ",".join(sorted({g for g in groups if any(p.get("group") == g for p in spec["patches"])}))
    all_groups = ",".join(sorted(set(groups)))
    os.makedirs(work, exist_ok=True)

    exe = os.path.join(app, spec["executable"])
    patched = os.path.join(work, "TrialsFrontier.patched")
    cmd = PY + [os.path.join(ROOT, "scripts", "apply_patches.py"), SPEC]
    if cryptid(exe) == 0:
        cmd += [exe, patched]
    elif decrypted:
        cmd += [decrypted, patched]
    elif page:
        cmd += [exe, patched, "--page", page]
    else:
        sys.exit("the app's executable is encrypted: give --decrypted <executable> or --page <page.bin> "
                 "(a private helper)")
    run(cmd + (["--with", exe_groups] if exe_groups else []), dry)

    ipa_cmd = PY + [os.path.join(ROOT, "scripts", "build_ipa.py"), app, patched,
                    os.path.join(work, "TrialsFrontier-7.9.0-patched.ipa"), "--spec", SPEC]
    if all_groups:
        ipa_cmd += ["--with", all_groups]
    if server == "embedded":
        inapp = os.path.join(work, "inapp")
        run(PY + [os.path.join(ROOT, "scripts", "build_inapp.py"), inapp, "--target", "dylib"], dry)
        ipa_cmd += ["--inapp", inapp]
        if avatars:
            ipa_cmd += ["--avatars", avatars]
        if wr and wr_ids:
            ipa_cmd += ["--world-records", wr, "--world-record-ids", wr_ids]
    run(ipa_cmd, dry)

    if install:
        inst = PY + [os.path.join(ROOT, "scripts", "install_playcover.py"), SPEC, app,
                     "--ipa", os.path.join(work, "TrialsFrontier-7.9.0-patched.ipa")]
        if keymap:
            inst += ["--keymap", os.path.join(ROOT, "playcover", "trials-frontier-keymap.plist")]
        run(inst, dry)
    print(f"done: {os.path.join(work, 'TrialsFrontier-7.9.0-patched.ipa')} (server: {server}; options: {', '.join(extra) or 'none'})")


if __name__ == "__main__":
    main()
