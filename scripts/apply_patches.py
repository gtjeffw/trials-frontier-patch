"""Apply the byte patches from a patch spec to the decrypted TrialsFrontier executable.

Usage: python3 -I apply_patches.py <spec.json> <executable in> <executable out> [--only id,id] [--groups g,g]
                                   [--with g,g]

By default every patch in the spec's "groups" is applied; patches in "optional_groups" (e.g. local-services) only
with --with (on top of the default groups) or when named in --groups. The default build is checked against
sha256.patched_executable, a --with build against sha256.patched_executable_with["<sorted,groups>"].

Input: an unencrypted executable of your own copy of 7.9.0 (arm64). If it is byte-identical to the reference
(sha256.decrypted_executable), the output is byte-for-byte reproducible and checked against the recorded hashes.
Decryption tools differ in details (e.g. code signature, header bytes), so another executable is accepted when it
is the same build and the same code: Mach-O UUID, not encrypted (cryptid 0), the formerly encrypted range equal to
the reference (sha256.decrypted_page), and every patch site holding exactly the original bytes.
"""
import json
import os
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


only, groups, extra = opt("--only"), opt("--groups"), opt("--with")
spec_path, src, dst = sys.argv[1:4]
spec = json.load(open(spec_path))
data = open(src, "rb").read()

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
for p in spec["patches"]:
    if p.get("group") in optional and p["group"] not in with_groups and not (selected_groups and p["group"] in selected_groups):
        continue
    if selected and p["id"] not in selected:
        continue
    if selected_groups and p.get("group") not in selected_groups:
        continue
    off = int(p["vmaddr"], 16) - base
    old, new = bytes.fromhex(p["original"]), bytes.fromhex(p["replacement"])
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
if with_groups:
    expected = spec["sha256"].get("patched_executable_with", {}).get(",".join(sorted(with_groups)))
print(f"wrote {dst} sha256={digest}")
if reference and not selected and not selected_groups and expected and digest != expected:
    sys.exit(f"patched sha256 does not match the spec ({expected})")
