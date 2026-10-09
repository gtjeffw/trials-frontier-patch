"""Apply the byte patches from a patch spec to the decrypted TrialsFrontier executable.

Usage: python3 -I apply_patches.py <spec.json> <executable in> <executable out> [--only id,id] [--groups g,g]
                                   [--with g,g]

By default every patch in the spec's "groups" is applied; patches in "optional_groups" (e.g. local-services) only
with --with (on top of the default groups) or when named in --groups. The default build is checked against
sha256.patched_executable, a --with build against sha256.patched_executable_with["<sorted,groups>"].

Input may be the decrypted executable, or the encrypted one plus --page <page.bin> from a private helper.
Every input and patch site is checked against the spec (sha256 / original bytes) before anything is written,
so the output is byte-for-byte reproducible.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from macho import apply_decrypted_page, sha256, text_section_offset  # noqa: E402


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


page_path, only, groups, extra = opt("--page"), opt("--only"), opt("--groups"), opt("--with")
spec_path, src, dst = sys.argv[1:4]
spec = json.load(open(spec_path))
data = open(src, "rb").read()

if page_path:
    if sha256(data) != spec["sha256"]["encrypted_executable"]:
        sys.exit("encrypted executable sha256 does not match the spec")
    data = apply_decrypted_page(data, open(page_path, "rb").read())
if sha256(data) != spec["sha256"]["decrypted_executable"]:
    sys.exit(f"decrypted executable sha256 {sha256(data)} does not match the spec")

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
        sys.exit(f"{p['id']}: unexpected bytes {cur.hex()} at {p['vmaddr']} (expected {old.hex()})")
    out[off:off + len(new)] = new
    print(f"applied {p['id']} @ {p['vmaddr']}")

open(dst, "wb").write(out)
os.chmod(dst, 0o755)
digest = sha256(bytes(out))
expected = spec["sha256"].get("patched_executable")
if with_groups:
    expected = spec["sha256"].get("patched_executable_with", {}).get(",".join(sorted(with_groups)))
print(f"wrote {dst} sha256={digest}")
if not selected and not selected_groups and expected and digest != expected:
    sys.exit(f"patched sha256 does not match the spec ({expected})")
