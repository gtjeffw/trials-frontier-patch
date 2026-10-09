"""Apply the byte patches from a patch spec to the decrypted TrialsFrontier executable.

Usage: python3 -I apply_patches.py <spec.json> <executable in> <executable out> [--only id,id]

Input may be the decrypted executable, or the encrypted one plus --page <page.bin> from a private helper.
Every input and patch site is checked against the spec (sha256 / original bytes) before anything is written,
so the output is byte-for-byte reproducible.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from macho import apply_decrypted_page, sha256  # noqa: E402


def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


page_path, only = opt("--page"), opt("--only")
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
out = bytearray(data)
selected = set(only.split(",")) if only else None
for p in spec["patches"]:
    if selected and p["id"] not in selected:
        continue
    off = int(p["vmaddr"], 16) - base
    old, new = bytes.fromhex(p["original"]), bytes.fromhex(p["replacement"])
    cur = bytes(out[off:off + len(old)])
    if cur != old:
        sys.exit(f"{p['id']}: unexpected bytes {cur.hex()} at {p['vmaddr']} (expected {old.hex()})")
    out[off:off + len(new)] = new
    print(f"applied {p['id']} @ {p['vmaddr']}")

open(dst, "wb").write(out)
os.chmod(dst, 0o755)
digest = sha256(bytes(out))
expected = spec["sha256"].get("patched_executable")
print(f"wrote {dst} sha256={digest}")
if not selected and expected and digest != expected:
    sys.exit(f"patched sha256 does not match the spec ({expected})")
