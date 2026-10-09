"""Extract one app's files from an unencrypted iOS backup into a normal directory tree.

Usage: python3 -I extract_app_domain.py <backup_dir_with_Manifest.db> <out_dir> [bundle_id]
"""
import os
import shutil
import sqlite3
import sys

backup, out = sys.argv[1], sys.argv[2]
bundle = sys.argv[3] if len(sys.argv) > 3 else "com.ubisoft.redlynx.trialsfrontier"

# Manifest.db is in WAL mode; immutable=1 opens it without creating -wal/-shm files in the backup
db = sqlite3.connect(f"file:{os.path.abspath(os.path.join(backup, 'Manifest.db'))}?immutable=1", uri=True)
rows = db.execute(
    "SELECT fileID, domain, relativePath, flags FROM Files "
    "WHERE domain = ? OR domain LIKE ? OR domain LIKE ? ORDER BY domain, relativePath",
    (f"AppDomain-{bundle}", f"AppDomainGroup-%{bundle.rsplit('.', 1)[0]}%", f"AppDomainPlugin-{bundle}%"),
).fetchall()

copied = 0
for file_id, domain, rel, flags in rows:
    dest = os.path.abspath(os.path.join(out, domain, rel))
    if not dest.startswith(os.path.abspath(out) + os.sep):
        continue  # refuse path traversal
    if flags == 2:  # directory
        os.makedirs(dest, exist_ok=True)
    elif flags == 1:  # regular file
        src = os.path.join(backup, file_id[:2], file_id)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if os.path.exists(src):
            shutil.copy2(src, dest)
            copied += 1
        else:
            print(f"missing blob for {domain}/{rel}", file=sys.stderr)

print(f"{len(rows)} manifest entries, {copied} files copied to {out}")
