"""Build (and optionally install) a patched Trials Frontier 7.9.0 from a copy of the app (preferably your own).

Usage:
  python3 -I build.py --app <TrialsFrontier.app> --work <work dir>
                      [--decrypted <unencrypted TrialsFrontier executable of that copy>]
                      [--server embedded|external|none] [--with group,group,...]
                      [--avatars <dir>] [--community [<layer dir>]]
                      [--bundle-id <id>] [--display-name <name>] [--port N]
                      [--install] [--keymap] [--dry-run]

Steps (each verified against the sha256 values in patches/trials-frontier-7.9.0.json where they exist):
  1. executable: --decrypted if given, else the app's own if it is not encrypted (cryptid 0); see the README,
     "Getting the game files";
  2. scripts/apply_patches.py: the default groups (compat, privacy, offline) plus the chosen options;
  3. with --server embedded: scripts/build_inapp.py builds libTFLocalServices.dylib (needs Xcode);
  4. scripts/build_ipa.py: a reproducible .ipa in --work;
  5. with --install: scripts/install_playcover.py hands it to PlayCover and copies the texture packs the game only
     loads from Library/Caches/DLC (and the keyboard map with --keymap). Close the game first.

--server:   embedded (default) = the game serves leaderboards, ghosts and login itself on 127.0.0.1:7979
                                 (local-services + embedded-server);
            external = local-services only; run server/local_services.py (or tfserver) yourself, e.g. for development;
            none     = no local services (everything online stays off).
--with:     optional extras: unlimited-fuel, unlimited-gems, coins-for-gems, unlock-bikes, unlock-legendary-bikes,
            unlock-special-bikes, open-all-levels, orphan-levels, dev-levels, file-sharing (see README). Without
            unlimited-fuel/-gems the game's own fuel (refills over time) and gems (earned by playing) work offline.
--community: build a community layer into the app (other riders' bundles, the 2019 world records; see
            scripts/community.py): the given layer folder, or the one `community.py update` made. Used when the
            game's data has no installed layer (`community.py install`, the way to update it later).
--bundle-id / --display-name: a second copy next to the original app, with its own data: on iPhone/iPad (then sign
            with scripts/sign_ios.py) or in PlayCover (e.g. a fresh game besides your own).
--port:     the local services port (the game's server on 127.0.0.1, shared by all apps on the machine). Default:
            7979 for the original app; for a --bundle-id copy one derived from the bundle id (7980-8979), so copies never
            reach each other's server. With --server external, run the server with the same --port.
"""
import hashlib
import json
import os
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SPEC = os.path.join(ROOT, "patches", "trials-frontier-7.9.0.json")
PY = [sys.executable, "-I"]
COMMUNITY_HOME = os.environ.get("TF_COMMUNITY_HOME") or os.path.expanduser(
    "~/Library/Application Support/trials-frontier-patch/community")


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


ARCH = {12: "armv7 (32-bit)", 0x0100000C: "arm64"}


def macho_info(path):
    """(cpu type, uuid) of a thin Mach-O; for a fat file, the cpu types of its slices and None."""
    data = open(path, "rb").read(65536)
    if struct.unpack_from(">I", data, 0)[0] == 0xCAFEBABE:
        n = struct.unpack_from(">I", data, 4)[0]
        return [struct.unpack_from(">I", data, 8 + 20 * i)[0] for i in range(n)], None
    magic, cpu, _, _, ncmds = struct.unpack_from("<5I", data, 0)
    if magic != 0xFEEDFACF and magic != 0xFEEDFACE:
        return None, None
    off = 32 if magic == 0xFEEDFACF else 28
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<2I", data, off)
        if cmd == 0x1B:  # LC_UUID
            u = data[off + 8:off + 24].hex().upper()
            return cpu, f"{u[:8]}-{u[8:12]}-{u[12:16]}-{u[16:20]}-{u[20:]}"
        off += size
    return cpu, None


def check_packs(app, spec):
    """Compare the app's content packs with the reference 7.9.0 app (spec app_packs): stop if a core pack is missing,
    report other missing or different packs. Returns the names of the missing ones."""
    info = spec.get("app_packs", {})
    missing, different = [], []
    for rel, ref in info.get("files", {}).items():
        path = os.path.join(app, rel)
        if not os.path.exists(path):
            missing.append(rel)
        elif os.path.getsize(path) != ref["size"] or hashlib.sha256(open(path, "rb").read()).hexdigest() != ref["sha256"]:
            different.append(rel)
    core = [m for m in missing if m in info.get("core", [])]
    if core:
        sys.exit(f"{app}: core content packs are missing: {', '.join(core)}. You'll need to find another source for "
                 "them; without them the game cannot start.")
    if missing:
        print(f"WARNING: {len(missing)} content pack(s) missing from your copy of the app:\n  "
              + "\n  ".join(missing) + "\nYou'll need to find another source for these packs (put them into the app "
              "bundle at the paths above). The build goes on without them; parts of the game that use them (tracks, "
              "bikes, sounds or artwork) may be missing or black.")
    if different:
        print(f"note: {len(different)} content pack(s) differ from the reference 7.9.0 app (another version, or "
              f"modified): {', '.join(different)}. Content edits to them may fail.")
    if not missing and not different:
        print(f"content packs: all {len(info.get('files', {}))} present and identical to the reference")
    return missing


def check_executable(path, spec):
    cpu, uuid = macho_info(path)
    if isinstance(cpu, list):
        arches = ", ".join(ARCH.get(c, hex(c)) for c in cpu)
        if 0x0100000C in cpu:
            sys.exit(f"{path}: universal executable ({arches}); extract the arm64 slice first: "
                     f"lipo -thin arm64 -output <file> {path}, then pass it with --decrypted")
    if cpu != 0x0100000C:
        arch = ", ".join(ARCH.get(c, hex(c)) for c in cpu) if isinstance(cpu, list) else ARCH.get(cpu, "unknown")
        sys.exit(f"{path}: {arch} executable; the patches are for the arm64 build of {spec['version']} "
                 f"(Mach-O UUID {spec['macho_uuid']}). App Store copies are thinned per device: use the copy from a "
                 f"64-bit iPhone/iPad (the content packs of other copies are the same; pass your arm64 executable "
                 f"with --decrypted)")
    if uuid != spec["macho_uuid"]:
        sys.exit(f"{path}: Mach-O UUID {uuid}, expected {spec['macho_uuid']} (TrialsFrontier {spec['version']}, arm64)")


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
    if not dry and subprocess.run(cmd).returncode != 0:
        sys.exit(f"failed: {os.path.basename(cmd[2])} (see the message above)")


def main():
    app, work = opt("--app"), opt("--work")
    decrypted = opt("--decrypted")
    server = opt("--server", default="embedded")
    extra = [g for g in (opt("--with", default="") or "").split(",") if g]
    avatars = opt("--avatars")
    community = None
    if "--community" in sys.argv:  # optional value: default the layer of scripts/community.py
        i = sys.argv.index("--community")
        nxt = sys.argv[i + 1] if i + 1 < len(sys.argv) else None
        community = nxt if nxt and not nxt.startswith("--") else os.path.join(COMMUNITY_HOME, "layer")
        del sys.argv[i:i + (2 if nxt and not nxt.startswith("--") else 1)]
    bundle_id, display_name = opt("--bundle-id"), opt("--display-name")
    port = opt("--port")
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
    # Local services port: every copy serves itself on 127.0.0.1, which all apps on a Mac share. The original app keeps
    # the spec's port (7979); a copy with its own --bundle-id gets its own port, derived from the bundle id, so two
    # copies running at once never reach each other's server (a login there would make the game switch accounts).
    if "local-services" in groups:
        if port is None:
            port = (spec["local_services_port"] if not bundle_id or bundle_id == spec["bundle_id"]
                    else 7980 + int(hashlib.sha256(bundle_id.encode()).hexdigest(), 16) % 1000)
        port = str(int(port))
    elif port:
        sys.exit("--port needs local services (--server embedded or external)")
    exe_groups = ",".join(sorted({g for g in groups if any(p.get("group") == g for p in spec["patches"])}))
    all_groups = ",".join(sorted(set(groups)))
    os.makedirs(work, exist_ok=True)

    exe = os.path.join(app, spec["executable"])
    check_executable(decrypted or exe, spec)
    check_packs(app, spec)
    patched = os.path.join(work, "TrialsFrontier.patched")
    cmd = PY + [os.path.join(ROOT, "scripts", "apply_patches.py"), SPEC]
    if decrypted:
        cmd += [decrypted, patched]
    elif cryptid(exe) == 0:
        cmd += [exe, patched]
    else:
        sys.exit("the app's executable is encrypted (App Store copies are): give --decrypted <an unencrypted "
                 "executable of that copy>; see the README, \"Getting the game files\"")
    run(cmd + (["--with", exe_groups] if exe_groups else []) + (["--port", port] if port else []), dry)

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
        if community:
            ipa_cmd += ["--community", community]
    if bundle_id:
        ipa_cmd += ["--bundle-id", bundle_id]
    if port:
        ipa_cmd += ["--port", port]
    if display_name:
        ipa_cmd += ["--display-name", display_name]
    run(ipa_cmd, dry)

    if install:
        inst = PY + [os.path.join(ROOT, "scripts", "install_playcover.py"), SPEC, app,
                     "--ipa", os.path.join(work, "TrialsFrontier-7.9.0-patched.ipa")]
        if keymap:
            inst += ["--keymap", os.path.join(ROOT, "playcover", "trials-frontier-keymap.plist")]
        if bundle_id:
            inst += ["--bundle-id", bundle_id]
        if port:
            inst += ["--port", port]
        run(inst, dry)
    print(f"done: {os.path.join(work, 'TrialsFrontier-7.9.0-patched.ipa')} (server: {server}"
          + (f" on port {port}" if port else "") + f"; options: {', '.join(extra) or 'none'})")


if __name__ == "__main__":
    main()
