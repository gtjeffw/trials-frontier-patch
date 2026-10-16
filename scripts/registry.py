"""The community registry: one list of every published ghost bundle that passed verification.

Usage:
  python3 -I registry.py add   <registry.json> <owner/repo> [--via <text>]   verify one bundle; add or update it
  python3 -I registry.py issue <registry.json> <event.json>                  a GitHub issue asking to add a bundle
  python3 -I registry.py crawl <registry.json>                               find (GitHub topic) and re-verify all
  python3 -I registry.py check <registry.json>

The registry lives in its own public repository (REGISTRY below), whose GitHub Action runs this script: when an
issue is opened (ghost_bundle.py publish offers to open one, titled "bundle: <owner/repo>"), and nightly (crawl). An
entry is added or updated only when ghost_bundle.verify_published accepts the bundle: valid, and every commit made
through GitHub by the publisher its manifest names. The registry only points to bundles: scripts/community.py
still fetches and verifies each one itself, so the registry cannot vouch for data it does not hold.

registry.json: {"format": "trials-frontier-registry", "format_version": 1, "updated": <UTC time>,
  "bundles": [{"repo", "publisher", "rider", "game_hash", "profile_sha256", "license", "commit", "manifest_sha256",
               "added", "verified", "status": "ok" | "failing", "note"?}],
  "blocked": [<owner/repo>, ...]}
A bundle that stops verifying is kept as "failing" (with the reason) until it verifies again; one that is gone from
GitHub too. `issue` prints the reply for the issue (Markdown) and exits 0 when the bundle was accepted, 1 otherwise,
2 when the issue is not a bundle request (left for a person).
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ghost_bundle as gb  # noqa: E402

REGISTRY = "gtjeffw/trials-frontier-registry"
FORMAT, VERSION = "trials-frontier-registry", 1
TOPIC = "trials-frontier-bundle"


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(path):
    if not os.path.exists(path):
        return {"format": FORMAT, "format_version": VERSION, "updated": None, "bundles": [], "blocked": []}
    reg = json.load(open(path))
    if reg.get("format") != FORMAT or reg.get("format_version") != VERSION:
        raise ValueError(f"{path}: not a {FORMAT} (format {VERSION})")
    if not isinstance(reg.get("bundles"), list) or not isinstance(reg.get("blocked", []), list):
        raise ValueError(f"{path}: bad layout")
    for b in reg["bundles"]:
        if not gb.REPO_RE.fullmatch(str(b.get("repo"))) or b.get("status") not in ("ok", "failing"):
            raise ValueError(f"{path}: bad entry {b.get('repo')!r}")
    return reg


def save(path, reg, before=None):
    """Write the registry; "updated" changes only when an entry did (so a quiet nightly run commits nothing)."""
    reg["bundles"].sort(key=lambda b: b["repo"].lower())
    if before is None or json.dumps(dict(reg, updated=None), sort_keys=True) != json.dumps(dict(before, updated=None),
                                                                                          sort_keys=True):
        reg["updated"] = now()
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(reg, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def add(reg, full, via=None):
    """Verify one bundle and add or update its entry. Returns (accepted, message)."""
    full = full.strip().removeprefix("https://github.com/").strip("/").removesuffix(".git")
    if not gb.REPO_RE.fullmatch(full) or ".." in full:
        return False, f"`{full}` is not a GitHub repository name (owner/repo)."
    if full.lower() in {r.lower() for r in reg.get("blocked", [])}:
        return False, f"`{full}` is blocked in this registry."
    entry = next((b for b in reg["bundles"] if b["repo"].lower() == full.lower()), None)
    try:
        v = gb.verify_published(full)
    except gb.BundleError as e:
        if entry and (entry.get("status") != "failing" or entry.get("note") != str(e)[:300]):
            entry.update(status="failing", note=str(e)[:300])  # keep what was known, mark it
        return False, f"`{full}` did not verify: {e}"
    m = v["manifest"]
    new = {"repo": full, "publisher": v["publisher"], "rider": m["rider"]["name"], "game_hash": m["rider"]["game_hash"],
           "profile_sha256": m["rider"]["profile_sha256"], "license": m["license"], "commit": v["commit"],
           "manifest_sha256": v["manifest_sha256"], "verified": now(), "status": "ok"}
    if via:
        new["via"] = via
    if entry:
        changed = entry.get("commit") != new["commit"] or entry.get("status") != "ok"
        if not changed:  # the same commit verified again: nothing to record (no nightly churn)
            return True, f"`{full}` re-verified (unchanged): {m['rider']['name']}."
        entry.pop("note", None)
        entry.update(new)
        return True, (f"`{full}` updated to {new['commit'][:10]}" if changed else f"`{full}` re-verified (unchanged)") + \
            f": {m['rider']['name']}, {len(m['results'])} best times, {len(m['ghosts'])} ghosts."
    reg["bundles"].append(dict(new, added=new["verified"]))
    return True, (f"`{full}` added: {m['rider']['name']}, {len(m['results'])} best times, {len(m['ghosts'])} ghosts, "
                  f"every commit signed by GitHub for {v['publisher']}.")


def issue_request(event):
    """The repository named by an issue opened as "bundle: <owner/repo>" (title, or a `repo: owner/repo` line in the
    body). None when the issue is something else."""
    iss = event.get("issue") or {}
    m = re.match(r"\s*bundle:\s*(\S+)\s*$", str(iss.get("title", "")), re.I)
    if m:
        return m.group(1)
    m = re.search(r"(?m)^\s*repo:\s*(\S+)\s*$", str(iss.get("body") or ""))
    return m.group(1) if m and str(iss.get("title", "")).lower().startswith("bundle") else None


def head_commit(full):
    """The newest commit of a repository (one small API call), or None if it cannot be read."""
    try:
        c = gb.github_get(f"repos/{full}/commits?per_page=1")
        return c[0]["sha"] if c else None
    except gb.BundleError:
        return None


def crawl(reg):
    """Find bundles (GitHub topic) and keep the listed ones current, doing only the work that is new: a repository
    whose last push (from the search result) is the one recorded is skipped without any further request; otherwise
    its newest commit is asked for, and only a new commit, or a bundle never seen, is downloaded and verified. A
    failing bundle is retried when its repository gets a new commit."""
    pushed = {}
    page = 1
    while page <= 10:
        res = gb.github_get(f"search/repositories?q=topic:{TOPIC}&per_page=100&page={page}")
        for r in res.get("items", []):
            pushed[r["full_name"].lower()] = (r["full_name"], r.get("pushed_at"))
        if len(res.get("items", [])) < 100:
            break
        page += 1
    for b in reg["bundles"]:  # listed bundles whose topic was removed are still kept current
        pushed.setdefault(b["repo"].lower(), (b["repo"], None))
    listed = {b["repo"].lower(): b for b in reg["bundles"]}
    out = []
    for key in sorted(pushed):
        full, at = pushed[key]
        entry = listed.get(key)
        if entry and at and entry.get("pushed_at") == at:
            out.append(f"same {full}: no push since it was checked")
            continue
        if entry:
            head = head_commit(full)
            done = entry.get("commit") if entry["status"] == "ok" else entry.get("failed_commit")
            if head and head == done:
                if at and entry.get("pushed_at") != at:
                    entry["pushed_at"] = at
                out.append(f"same {full}: newest commit {head[:10]} already checked")
                continue
        ok, msg = add(reg, full, via="crawl")
        entry = next((b for b in reg["bundles"] if b["repo"].lower() == key), None)
        if entry is not None:
            if at:
                entry["pushed_at"] = at
            if not ok:
                entry["failed_commit"] = head_commit(full)
            else:
                entry.pop("failed_commit", None)
        out.append(("ok   " if ok else "FAIL ") + msg)
    return out


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("add", "issue", "crawl", "check"):
        sys.exit(__doc__)
    cmd, path = sys.argv[1], sys.argv[2]
    reg = load(path)
    before = json.loads(json.dumps(reg))
    if cmd == "check":
        ok = sum(b["status"] == "ok" for b in reg["bundles"])
        print(f"ok: {len(reg['bundles'])} bundles ({ok} verified, {len(reg['bundles']) - ok} failing), "
              f"{len(reg.get('blocked', []))} blocked")
    elif cmd == "add" and len(sys.argv) >= 4:
        via = sys.argv[sys.argv.index("--via") + 1] if "--via" in sys.argv else None
        ok, msg = add(reg, sys.argv[3], via)
        save(path, reg, before)
        print(msg)
        sys.exit(0 if ok else 1)
    elif cmd == "issue" and len(sys.argv) >= 4:
        event = json.load(open(sys.argv[3]))
        full = issue_request(event)
        if not full:
            print("Not a bundle request; left for a person.")
            sys.exit(2)
        ok, msg = add(reg, full, via=f"issue #{(event.get('issue') or {}).get('number')}")
        save(path, reg, before)
        print(("Thanks! " if ok else "Sorry, not added. ") + msg +
              ("" if ok else "\n\nPublish with `scripts/ghost_bundle.py publish` (every commit must be made through "
                             "GitHub by the publisher the bundle names), then open a new issue."))
        sys.exit(0 if ok else 1)
    elif cmd == "crawl":
        for line in crawl(reg):
            print(line)
        save(path, reg, before)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
