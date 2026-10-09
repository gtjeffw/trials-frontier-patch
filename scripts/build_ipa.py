"""Build a reproducible .ipa from an original TrialsFrontier.app bundle and a patched executable.

Usage: python3 -I build_ipa.py <TrialsFrontier.app from device> <patched executable> <out.ipa>
       [--spec patches/trials-frontier-7.9.0.json] [--groups g,g] [--with g,g]

With --spec, the spec's "plist_patches" (optionally limited to --groups) are applied to the bundle's plists;
plists are re-serialised as sorted binary plists so the output stays reproducible. "content_patches" edit files
inside the bundle's own datapacks (scripts/datapack.py); like executable patches, those in "optional_groups" apply
only with --with (or when named in --groups).

The original bundle is copied unchanged except: SC_Info/ (per-account FairPlay data) is dropped and the
executable is replaced. Zip entries are sorted, stored uncompressed, with fixed timestamps and permissions,
so the same inputs always give the same .ipa bytes. The result is unsigned in practice (the original
Apple signature no longer matches); PlayCover re-signs on install.
"""
import hashlib
import json
import os
import plistlib
import stat
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import datapack  # noqa: E402

def opt(name):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return None


spec_path, groups, extra = opt("--spec"), opt("--groups"), opt("--with")
app_dir, exe_path, out = sys.argv[1:4]
plist_edits, content_patches = {}, {}
if spec_path:
    spec = json.load(open(spec_path))
    selected = set(groups.split(",")) if groups else None
    optional = set(spec.get("optional_groups", {}))
    with_groups = set(extra.split(",")) if extra else set()
    if with_groups - optional:
        sys.exit(f"--with: not an optional group: {', '.join(sorted(with_groups - optional))}")

    def wanted(group):
        if group in optional:
            return group in with_groups or bool(selected and group in selected)
        return not selected or group in selected

    for pp in spec.get("plist_patches", []):
        if wanted(pp["group"]):
            plist_edits.setdefault(pp["file"], {}).update(pp["set"])
    for cp in spec.get("content_patches", []):
        if wanted(cp["group"]):
            content_patches.setdefault(cp["pack"], []).append(cp)
app_name = os.path.basename(os.path.normpath(app_dir))
exe_name = "TrialsFrontier"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)
SKIP_TOP = {"SC_Info"}

entries = []
for root, dirs, files in os.walk(app_dir):
    rel_root = os.path.relpath(root, app_dir)
    if rel_root.split(os.sep)[0] in SKIP_TOP:
        continue
    dirs.sort()
    for name in sorted(files):
        if name == ".DS_Store":
            continue
        rel = os.path.normpath(os.path.join(rel_root, name))
        entries.append(rel)
entries.sort()


def add(z, arcname, data, executable):
    info = zipfile.ZipInfo(arcname, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3  # unix, so permissions are honoured
    mode = 0o755 if executable else 0o644
    info.external_attr = (stat.S_IFREG | mode) << 16
    z.writestr(info, data)


with zipfile.ZipFile(out, "w") as z:
    for rel in entries:
        arc = f"Payload/{app_name}/{rel}"
        if rel == exe_name:
            add(z, arc, open(exe_path, "rb").read(), True)
        elif rel in plist_edits:
            pl = plistlib.load(open(os.path.join(app_dir, rel), "rb"))
            pl.update(plist_edits[rel])
            add(z, arc, plistlib.dumps(pl, fmt=plistlib.FMT_BINARY, sort_keys=True), False)
            print(f"patched {rel}: {plist_edits[rel]}")
        elif rel in content_patches:
            pack = open(os.path.join(app_dir, rel), "rb").read()
            for cp in content_patches[rel]:
                pack = datapack.apply_content_patch(pack, cp)
                print(f"patched {rel}: {cp['id']} ({cp['file']})")
            add(z, arc, pack, False)
        else:
            src = os.path.join(app_dir, rel)
            add(z, arc, open(src, "rb").read(), bool(os.stat(src).st_mode & 0o111))

h = hashlib.sha256(open(out, "rb").read()).hexdigest()
print(f"wrote {out} ({len(entries)} files) sha256={h}")
