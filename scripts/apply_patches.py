"""Apply the byte patches from a patch spec to the decrypted TrialsFrontier executable.

Usage: python3 -I apply_patches.py <spec.json> <executable in> <executable out> [--only id,id] [--groups g,g]
                                   [--with g,g] [--without g,g] [--port N]

By default every patch in the spec's "groups" is applied; patches in "optional_groups" (e.g. local-services) only
with --with (on top of the default groups) or when named in --groups. The default build is checked against
sha256.patched_executable, a --with build against sha256.patched_executable_with["<sorted,groups>"]. --without drops
default groups the spec lists in "removable_groups" (unlimited-fuel, unlimited-gems: the game's own fuel and gems);
their hashes are recorded under the same key with "-<group>" entries after the --with groups.

Input: an unencrypted executable of your own copy of 7.9.0 (arm64). If it is byte-identical to the reference
(sha256.decrypted_executable), the output is byte-for-byte reproducible and checked against the recorded hashes.
A copy whose cryptoff/cryptsize were zeroed along with cryptid gets them restored from the spec first, so it can
still be byte-identical to the reference.
Decryption tools differ in details (e.g. code signature, header bytes), so another executable is accepted when it
is the same build and the same code: Mach-O UUID, not encrypted (cryptid 0), the formerly encrypted range equal to
the reference (sha256.decrypted_page), and every patch site holding exactly the original bytes.
"""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from macho import encryption_info, macho_uuid, sha256, text_section_offset  # noqa: E402


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


only, groups, extra, port = opt("--only"), opt("--groups"), opt("--with"), opt("--port")
without = opt("--without")
spec_path, src, dst = sys.argv[1:4]
spec = json.load(open(spec_path))
# --port: the local services port written into the game's service URLs ("http://127.0.0.1:7979..."), so that several
# copies (each with its own server) never reach each other's server. Same number of digits, so no lengths change.
default_port = int(spec.get("local_services_port", 7979))
port = int(port) if port else default_port
if not 1000 <= port <= 9999:
    sys.exit("--port: a four-digit port (1000-9999)")
port_from, port_to = b"127.0.0.1:%d" % default_port, b"127.0.0.1:%d" % port
data = open(src, "rb").read()

# some tools zero cryptoff/cryptsize along with cryptid; restore them so such a copy can match the reference
try:
    lc, cryptoff, cryptsize, cryptid = encryption_info(data)
    if cryptid == 0 and cryptoff == 0 and cryptsize == 0:
        data = bytearray(data)
        struct.pack_into("<2I", data, lc + 8, spec["encryption"]["cryptoff"], spec["encryption"]["cryptsize"])
        data = bytes(data)
except ValueError:
    pass

reference = sha256(data) == spec["sha256"]["decrypted_executable"]
if not reference:
    try:
        _, cryptoff, cryptsize, cryptid = encryption_info(data)
    except ValueError as e:
        sys.exit(f"{src}: not the expected executable ({e})")
    if macho_uuid(data) != spec["macho_uuid"]:
        sys.exit(f"{src}: Mach-O UUID {macho_uuid(data)}, expected {spec['macho_uuid']} (TrialsFrontier {spec['version']})")
    if cryptid != 0:
        sys.exit(f"{src}: the executable is still encrypted (cryptid {cryptid}); an unencrypted copy is needed")
    if sha256(data[cryptoff:cryptoff + cryptsize]) != spec["sha256"]["decrypted_page"]:
        sys.exit(f"{src}: the formerly encrypted code differs from the reference: not a correct decryption of "
                 f"{spec['version']}")
    print(f"note: {os.path.basename(src)} is not byte-identical to the reference executable (another decryption "
          "tool?) but is the same build and code; patching it (the output will not match the recorded hashes)")

base = int(spec["text_vmaddr_base"], 16)
text_start = text_section_offset(data)
out = bytearray(data)
selected = set(only.split(",")) if only else None
selected_groups = set(groups.split(",")) if groups else None
optional = set(spec.get("optional_groups", {}))
with_groups = set(extra.split(",")) if extra else set()
if with_groups - optional:
    sys.exit(f"--with: not an optional group: {', '.join(sorted(with_groups - optional))}")
without_groups = set(without.split(",")) if without else set()
if without_groups - set(spec.get("removable_groups", [])):
    sys.exit(f"--without: not a removable group: {', '.join(sorted(without_groups - set(spec.get('removable_groups', []))))}"
             f" (removable: {', '.join(spec.get('removable_groups', []))})")
for p in spec["patches"]:
    if p.get("group") in without_groups:
        continue
    if p.get("group") in optional and p["group"] not in with_groups and not (selected_groups and p["group"] in selected_groups):
        continue
    if selected and p["id"] not in selected:
        continue
    if selected_groups and p.get("group") not in selected_groups:
        continue
    off = int(p["vmaddr"], 16) - base
    old, new = bytes.fromhex(p["original"]), bytes.fromhex(p["replacement"])
    new = new.replace(port_from, port_to)
    if p.get("original_asm") == ["(zero padding)"] and (any(old) or off + len(old) > text_start):
        sys.exit(f"{p['id']}: code cave is not inside the zero padding before __text")
    cur = bytes(out[off:off + len(old)])
    if cur != old:
        sys.exit(f"{p['id']}: unexpected bytes {cur.hex()} at {p['vmaddr']} (expected {old.hex()})" +
                 ("" if reference else "\nthis executable differs from the reference beyond decryption (e.g. its "
                  "headers or code signature were changed by the tool that made it); use an unencrypted copy that "
                  "keeps the executable otherwise unchanged"))
    out[off:off + len(new)] = new
    print(f"applied {p['id']} @ {p['vmaddr']}")

open(dst, "wb").write(out)
os.chmod(dst, 0o755)
digest = sha256(bytes(out))
expected = spec["sha256"].get("patched_executable")
if with_groups or without_groups:
    key = ",".join(sorted(with_groups) + ["-" + g for g in sorted(without_groups)])
    expected = spec["sha256"].get("patched_executable_with", {}).get(key)
if port != default_port:
    expected = None  # the recorded hashes are for the default port
    print(f"local services port {port} (recorded hashes are for {default_port})")
print(f"wrote {dst} sha256={digest}")
if reference and not selected and not selected_groups and expected and digest != expected:
    sys.exit(f"patched sha256 does not match the spec ({expected})")
