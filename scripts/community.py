"""Race other riders in your patched game: a list of sources (ghost bundles, the 2019 world records), fetched into a
local cache, checked, and consolidated into a "community layer" that the local server (embedded or Python) reads.

Usage:
  python3 -I community.py list
  python3 -I community.py add <owner/repo | https://github.com/owner/repo | local bundle folder> [--unsigned-ok]
  python3 -I community.py remove <id>
  python3 -I community.py enable|disable <id>          e.g. disable world-records-2019
  python3 -I community.py discover [--add]             published bundles (GitHub topic) not in your list yet
  python3 -I community.py sync                         fetch or update every enabled source into the cache
  python3 -I community.py build                        consolidate the cache into the community layer
  python3 -I community.py install [--container <game data dir>]   put the layer into the game's data
  python3 -I community.py update [--container <dir>]   sync + build + install (install only if the game is closed)
  python3 -I community.py status

Sources: the defaults in community/sources.json of this repository (the patch author's bundle; the 2019 world
records, on unless you disable them), plus your own list, which can add sources and override the defaults
by id. A bundle from GitHub must be its publisher's: every commit made through GitHub by the account its manifest
names (signed by GitHub; ghost_bundle.py publish does that). Local folders, and sources added with --unsigned-ok,
are not checked that way.

Robust and incremental: sync replaces a source's cached copy only with a newer copy that passes every check
(validation as in ghost_bundle.py check, the publisher's GitHub-signed commits, pinned sha256 for the world
records); anything that fails keeps the last good copy. build always starts from scratch, so revised or removed
data in a source is reflected; it is deterministic for the same cache. The layer never touches your own results:
the server overlays it when it loads and never writes it into your store.

LICENCES: every source has its own licence (a bundle's manifest `license`, chosen by its publisher; the world
records are MIT). Using the layer in your own game is what the sources are published for. If you republish the
data, pass on a layer or an app with one built in, or serve it publicly (a website, a fan server), check and honour
the licence of EVERY source: some require credit (CC-BY, MIT's copyright notice), and future bundles may use other
licences. build writes NOTICE.md into the layer: each source, its publisher, licence and link.

Your data: ~/Library/Application Support/trials-frontier-patch/community/ (sources.json, cache/, layer/), or
$TF_COMMUNITY_HOME. Install target: <container>/Documents/LocalServices/community; default container PlayCover's
(com.ubisoft.redlynx.trialsfrontier). For iPhone/iPad: build.py --community puts the layer into the app, and
scripts/ios_device.py push-data copies Documents/LocalServices (including community/).
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ghost_bundle as gb  # noqa: E402

DEFAULT_SOURCES = os.path.join(HERE, "..", "community", "sources.json")
HOME = os.environ.get("TF_COMMUNITY_HOME") or os.path.expanduser(
    "~/Library/Application Support/trials-frontier-patch/community" if sys.platform == "darwin"
    else "~/.local/share/trials-frontier-patch/community")
DEFAULT_CONTAINER = os.path.expanduser("~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data")
LAYER_FORMAT, LAYER_VERSION = "trials-frontier-community", 1
COMMUNITY_BASE = 1_000_000_000  # content ids of community ghosts (the store's own count up from 1000)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe(source_id):
    return re.sub(r"[^A-Za-z0-9._-]+", "__", source_id)


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, path)


# ---- sources ----

def user_sources_path():
    return os.path.join(HOME, "sources.json")


def load_user():
    p = user_sources_path()
    return json.load(open(p)) if os.path.exists(p) else {"format": "trials-frontier-sources", "format_version": 1,
                                                          "sources": []}


def sources():
    """Defaults overridden by the user's entries (same id), in order: defaults first, then the user's additions."""
    out = {s["id"]: dict(s, origin="default") for s in json.load(open(DEFAULT_SOURCES))["sources"]}
    for s in load_user()["sources"]:
        out[s["id"]] = dict(out.get(s["id"], {}), **s, origin="default (changed)" if s["id"] in out else "yours")
    return list(out.values())


def set_user(source_id, **fields):
    u = load_user()
    entry = next((s for s in u["sources"] if s["id"] == source_id), None)
    if entry is None:
        entry = {"id": source_id}
        u["sources"].append(entry)
    entry.update(fields)
    os.makedirs(HOME, exist_ok=True)
    write_json(user_sources_path(), u)


def parse_repo(text):
    m = re.fullmatch(r"(?:https://github\.com/)?([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?", text)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def cmd_add(arg):
    unsigned = gb.opt("--unsigned-ok", True)
    if os.path.isdir(arg):
        path = os.path.abspath(arg)
        # the id ends up in the layer (and in apps built with it): never the local path
        taken = {x["id"]: x.get("path") for x in sources()}
        base = "local/" + re.sub(r"[^A-Za-z0-9._-]+", "-", os.path.basename(path.rstrip("/"))), 1
        sid, n = base
        while sid in taken and taken[sid] != path:
            n += 1
            sid = f"{base[0]}-{n}"
        set_user(sid, type="bundle", path=path, enabled=True, allow_unsigned=True)
        print(f"added local bundle {path} as {sid}")
        return
    repo = parse_repo(arg)
    if not repo:
        sys.exit(f"{arg}: not owner/repo, a GitHub URL or a folder")
    set_user(repo, type="bundle", repo=repo, enabled=True, **({"allow_unsigned": True} if unsigned else {}))
    print(f"added {repo} (run update to fetch it)")


def cmd_remove(source_id):
    u = load_user()
    if any(s["id"] == source_id for s in json.load(open(DEFAULT_SOURCES))["sources"]):
        set_user(source_id, enabled=False)
        print(f"{source_id} is a default source: disabled instead")
        return
    before = len(u["sources"])
    u["sources"] = [s for s in u["sources"] if s["id"] != source_id]
    if len(u["sources"]) == before:
        sys.exit(f"{source_id}: not in your list")
    write_json(user_sources_path(), u)
    cached = os.path.join(HOME, "cache", safe(source_id))
    shutil.rmtree(cached, ignore_errors=True)  # re-fetchable copy of public data
    print(f"removed {source_id}")


def cmd_enable(source_id, on):
    if not any(s["id"] == source_id for s in sources()):
        sys.exit(f"{source_id}: unknown source (see list)")
    set_user(source_id, enabled=on)
    print(f"{source_id} {'enabled' if on else 'disabled'} (run update to apply)")


def status_of(source_id):
    p = os.path.join(HOME, "cache", safe(source_id) + ".json")
    return json.load(open(p)) if os.path.exists(p) else {}


def cmd_list():
    for s in sources():
        st = status_of(s["id"])
        good = st.get("good")
        state = (f"cached {good['commit'][:10]} {good['fetched'][:10]}" + (f", signed by GitHub for {good['signed_by']}"
                 if good.get("signed_by") else "")) if good else "not fetched"
        if st.get("last_error"):
            state += f"; last sync failed: {st['last_error'][:80]}"
        lic = (good or {}).get("license") or s.get("license") or "?"
        print(f"{'on ' if s.get('enabled', True) else 'off'} {s['id']:45} {s['type']:18} {s['origin']:18} {lic:10} {state}")
        if s.get("note"):
            print(f"    {s['note']}")


def cmd_discover():
    add = gb.opt("--add", True)
    if shutil.which("gh") is None:
        sys.exit("needs the GitHub CLI (brew install gh)")
    r = subprocess.run(["gh", "search", "repos", "--topic", "trials-frontier-bundle", "--limit", "500",
                        "--json", "fullName,description,updatedAt"], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(r.stderr.strip())
    known = {s.get("repo") for s in sources()}
    new = [x for x in sorted(json.loads(r.stdout), key=lambda x: x["fullName"].lower()) if x["fullName"] not in known]
    for x in new:
        print(f"{x['fullName']:50} {x['updatedAt'][:10]}  {x['description'] or ''}")
        if add:
            set_user(x["fullName"], type="bundle", repo=x["fullName"], enabled=True)
    print(f"{len(new)} bundles not in your list" + (" (added; run update)" if add and new else
                                                    "" if not new else " (discover --add adds them)"))


# ---- sync ----

def sync_bundle(s, dest):
    """Fetch a bundle into a new folder; returns the status for it (raises on any problem)."""
    if s.get("path"):
        shutil.copytree(s["path"], dest, symlinks=True, ignore=shutil.ignore_patterns(".git", gb.EXPORT_OPTIONS))
        commit = "local-" + hashlib.sha256(open(os.path.join(dest, gb.MANIFEST), "rb").read()).hexdigest()[:12]
    else:
        url = f"https://github.com/{s['repo']}.git"
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", "-c", "core.symlinks=false", url, dest],
                           capture_output=True, text=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))
        if r.returncode != 0:
            raise gb.BundleError(f"could not fetch {url}: {r.stderr.strip()[:200]}")
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True).stdout.strip()
        shutil.rmtree(os.path.join(dest, ".git"))
    m = gb.check(dest)
    signed_by = None
    if s.get("repo") and not s.get("allow_unsigned"):
        publisher = (m.get("publisher") or {}).get("github")
        if not publisher:
            raise gb.BundleError("the manifest names no publisher")
        signed_by = gb.verify_repo(s["repo"], publisher, commit)
    published = gb.github_get(f"repos/{s['repo']}").get("created_at") if s.get("repo") else None
    return {"commit": commit, "fetched": now(), "signed_by": signed_by, "rider": m["rider"]["name"],
            "game_hash": m["rider"]["game_hash"], "created": m["created"], "published": published,
            "license": m["license"]}


def sync_wr(s, dest):
    os.makedirs(dest)
    for path, want in s["files"].items():
        url = f"https://raw.githubusercontent.com/{s['repo']}/{s['commit']}/{path}"
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read(20_000_000)
        if hashlib.sha256(data).hexdigest() != want:
            raise gb.BundleError(f"{path}: sha256 differs from the pinned value")
        open(os.path.join(dest, os.path.basename(path)), "wb").write(data)
    return {"commit": s["commit"], "fetched": now(), "signed_by": None, "license": s.get("license")}


def cmd_sync():
    cache = os.path.join(HOME, "cache")
    os.makedirs(cache, exist_ok=True)
    ok = failed = 0
    for s in sources():
        if not s.get("enabled", True):
            continue
        sid, target = s["id"], os.path.join(cache, safe(s["id"]))
        st = status_of(sid)
        tmp = tempfile.mkdtemp(prefix="tf-sync-", dir=cache)
        new = os.path.join(tmp, "src")
        try:
            if s["type"] == "bundle":
                info = sync_bundle(s, new)
            elif s["type"] == "trialstrackmap-wr":
                if st.get("good", {}).get("commit") == s["commit"] and all(
                        os.path.exists(os.path.join(target, os.path.basename(f))) for f in s["files"]):
                    print(f"ok   {sid}: unchanged (pinned {s['commit'][:10]})")
                    ok += 1
                    continue
                info = sync_wr(s, new)
            else:
                raise gb.BundleError(f"unknown source type {s['type']}")
            old = os.path.join(tmp, "old")
            if os.path.exists(target):
                os.rename(target, old)
            os.rename(new, target)
            changed = st.get("good", {}).get("commit") != info["commit"]
            st = {"good": info}
            print(f"ok   {sid}: {'updated to' if changed else 'unchanged'} {info['commit'][:10]}"
                  + (f", signed by GitHub for {info['signed_by']}" if info.get("signed_by") else
                     ", sha256 pinned" if s["type"] == "trialstrackmap-wr" else ", not checked (local folder)"))
            ok += 1
        except (gb.BundleError, OSError, ValueError) as e:
            st["last_error"], st["last_attempt"] = str(e), now()
            print(f"FAIL {sid}: {e}" + ("; keeping the last good copy" if st.get("good") else ""))
            failed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            write_json(os.path.join(cache, safe(sid) + ".json"), st)
    print(f"sync: {ok} ok, {failed} failed")
    return failed


# ---- build ----

def rider_name_ok(name):
    return name and not re.fullmatch(r"(?i)rider( [0-9A-F]{8})?", name)


def wr_results(folder):
    """2019 world records (dutscher/trialstrackmap, MIT): wrrider.json {riders[], tracks{siteId: {a|i: {n|d|c:
    {r, b, f, t}}}}} + ids.json (site id -> game level id "oid"; JSON with // comments). Categories: n = track<id>,
    d (donkey) = track<id | 0x10000>, c (crazy) = track<id | 0x100000>. Android (a) and iOS (i) both count."""
    wr = json.load(open(os.path.join(folder, "wrrider.json")))
    ids = re.sub(r"^\s*//.*$", "", open(os.path.join(folder, "ids.json")).read(), flags=re.M)
    site = {e["id"]: e["oid"] for e in json.loads(ids)}
    flags = {"n": 0, "d": 0x10000, "c": 0x100000}
    for sid, plats in sorted(wr["tracks"].items(), key=lambda kv: int(kv[0])):
        oid = site.get(int(sid))
        if oid is None:
            continue
        for plat in ("a", "i"):
            for cat, e in sorted((plats.get(plat) or {}).items()):
                if isinstance(e, dict) and cat in flags:
                    yield wr["riders"][e["r"]], oid | flags[cat], e["f"], e["t"], e["b"]


def claimed_id(profile_sha256):
    """Rider id of a bundle's own rider: from the profile id's sha256, so different players never share one."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "trials-frontier-rider:" + profile_sha256))


def result_entry(faults, ms, bike, source):
    return {"drivetime": ms, "data": (faults & 0xFF) | ((bike & 0x3F) << 8), "upgrades": 0, "submittime": 0,
            "score_value": 360000000 - ms - faults * 3600000, "extradata": 0, "source": source}


def cmd_build(out=None):
    out = out or os.path.join(HOME, "layer")
    cache = os.path.join(HOME, "cache")
    riders, results, ghosts, used, conflicts = {}, {}, {}, [], []
    claims = {}   # profile sha256 -> [(sort key, source id, manifest, folder)]
    mentions = {}  # game hash -> [(source id, ghost entry, folder, name)]

    def better(new, old):
        return old is None or ((new["data"] & 0xFF), new["drivetime"]) < ((old["data"] & 0xFF), old["drivetime"])

    def put_result(rid, lb, entry):
        board = results.setdefault("track%d" % lb, {})
        if better(entry, board.get(rid)):
            board[rid] = entry

    for s in sources():
        st = status_of(s["id"]).get("good")
        folder = os.path.join(cache, safe(s["id"]))
        if not s.get("enabled", True) or not st or not os.path.isdir(folder):
            continue
        try:
            if s["type"] == "bundle":
                m = gb.check(folder)  # the cache is checked again: it is only a folder on disk
                h = m["rider"]["game_hash"]
                # who claims a rider: verified publishers first, then the earliest published (GitHub's own creation
                # time of the repository, which the publisher cannot set; local folders only by their manifest date)
                claims.setdefault(m["rider"]["profile_sha256"], []).append(
                    ((not st.get("signed_by"), st.get("published") or "9999", m["created"], s["id"]), s["id"], m,
                     folder, st.get("signed_by")))
                for o in m.get("others", []):
                    for g in o["ghosts"]:
                        mentions.setdefault(o["game_hash"], []).append((s["id"], g, folder, o.get("name")))
                used.append({"id": s["id"], "type": "bundle", "commit": st["commit"], "signed_by": st.get("signed_by"),
                             "rider": m["rider"]["name"], "game_hash": h, "license": m["license"],
                             "url": f"https://github.com/{s['repo']}" if s.get("repo") else None})
            elif s["type"] == "trialstrackmap-wr":
                n = 0
                for name, lb, faults, ms, bike in wr_results(folder):
                    rid = str(uuid.uuid5(uuid.NAMESPACE_URL, "trialstrackmap-rider:" + name))
                    riders.setdefault(rid, {"name": name, "source": s["id"]})
                    put_result(rid, lb, result_entry(faults, ms, bike, "community " + s["id"]))
                    n += 1
                used.append({"id": s["id"], "type": s["type"], "commit": st["commit"], "results": n,
                             "license": s.get("license"), "attribution": s.get("attribution"),
                             "url": f"https://github.com/{s['repo']}/tree/{s['commit']}",
                             "license_text": open(os.path.join(folder, "LICENSE")).read()
                             if os.path.exists(os.path.join(folder, "LICENSE")) else None})
        except (gb.BundleError, OSError, ValueError, KeyError) as e:
            print(f"skip {s['id']}: {e}")

    # Identity: a bundle's own rider is known by profile_sha256 (from a 128-bit profile id: no collisions), riders
    # seen only as downloaded opponents by the game's 32-bit hash. The hash only *links* the two, and only when it
    # is unambiguous: exactly one claimed rider has it.
    best_ghost = {}  # (rider id, lb) -> (time, source id, file)
    def offer(rid, g, folder, source_id):
        key = (rid, g["leaderboard"])
        cand = (g["time_ms"], source_id, os.path.join(folder, g["file"]))
        if key not in best_ghost or cand < best_ghost[key]:
            best_ghost[key] = cand

    claimed_by_hash = {}
    for sha in sorted(claims):
        cl = sorted(claims[sha], key=lambda c: c[0])
        _, sid, m, folder, owner = cl[0]   # verified first, then the first published
        # the winner's own other bundles of the same rider are merged (best per leaderboard); other accounts' claims
        # are ignored and listed as conflicts
        mine = [c for c in cl if c is cl[0] or (owner and c[4] == owner)]
        rejected = [c[1] for c in cl if c not in mine]
        if rejected:
            conflicts.append({"profile_sha256": sha, "used": [c[1] for c in mine], "also_claimed_by": rejected,
                              "rule": "first published (GitHub's repository creation time) wins"})
        h = m["rider"]["game_hash"]
        rid = claimed_id(sha)
        claimed_by_hash.setdefault(h, []).append(rid)
        riders[rid] = {"name": m["rider"]["name"], "game_hash": h, "profile_sha256": sha, "source": sid}
        if "avatar" in m["rider"]:
            riders[rid]["avatar"] = os.path.join(folder, m["rider"]["avatar"]["file"])
        for _, csid, cm, cfolder, _ in mine:
            for e in cm["results"]:
                put_result(rid, e["leaderboard"], result_entry(e["faults"], e["time_ms"], e.get("bike") or 0,
                                                               "community " + csid))
            for g in cm["ghosts"]:
                offer(rid, g, cfolder, csid)
    for h, ids in sorted(claimed_by_hash.items()):
        if len(ids) > 1:
            conflicts.append({"game_hash": h, "riders": sorted(ids), "note": "32-bit hash shared by different riders; "
                              "downloaded-opponent ghosts with this hash are kept apart"})
    for h in sorted(mentions):
        ids = claimed_by_hash.get(h, [])
        rid = ids[0] if len(ids) == 1 else gb.rider_id(h)
        for sid, g, folder, name in sorted(mentions[h], key=lambda x: (x[0], x[1]["leaderboard"])):
            if rid not in riders:
                riders[rid] = {"name": "Rider " + h, "game_hash": h, "source": sid}
            if rider_name_ok(name) and riders[rid]["name"] == "Rider " + h:
                riders[rid]["name"] = name
            put_result(rid, g["leaderboard"], result_entry(0, g["time_ms"], g.get("bike") or 0, "community " + sid))
            offer(rid, g, folder, sid)

    # write the layer into a new folder, then swap
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="tf-layer-", dir=os.path.dirname(os.path.abspath(out)))
    os.makedirs(os.path.join(tmp, "ghosts"))
    os.makedirs(os.path.join(tmp, "avatars"))
    for i, ((rid, lb), (ms, sid, path)) in enumerate(sorted(best_ghost.items())):
        cid = COMMUNITY_BASE + i
        data = open(path, "rb").read()
        open(os.path.join(tmp, "ghosts", "%d.bin" % cid), "wb").write(data)
        ghosts[str(cid)] = {"profile": rid, "track_id": lb, "source": "community " + sid,
                            "metadata": {"track_id": lb, "drive_time": ms, "size": len(data)}}
    for rid, r in riders.items():
        avatar = r.pop("avatar", None)
        if avatar:
            shutil.copyfile(avatar, os.path.join(tmp, "avatars", rid + ".png"))
    layer = {"format": LAYER_FORMAT, "format_version": LAYER_VERSION, "sources": used, "conflicts": conflicts,
             "riders": riders, "results": results, "ghosts": ghosts}
    write_json(os.path.join(tmp, "community.json"), layer)
    write_notice(os.path.join(tmp, "NOTICE.md"), used)
    old = tmp + ".old"
    if os.path.exists(out):
        os.rename(out, old)
    os.rename(tmp, out)
    shutil.rmtree(old, ignore_errors=True)
    n_res = sum(len(b) for b in results.values())
    counts = {}
    for u in used:
        counts[u.get("license") or "unknown"] = counts.get(u.get("license") or "unknown", 0) + 1
    print("licences: " + ", ".join(f"{k} ({v})" for k, v in sorted(counts.items())) +
          " - fine for your own game; to republish, pass on or serve this data, honour each source's licence (NOTICE.md)")
    print(f"layer {out}: {len(used)} sources, {len(riders)} riders, {n_res} results, {len(ghosts)} ghosts"
          + (f"; {len(conflicts)} conflicts (see community.json)" if conflicts else ""))
    return out


def write_notice(path, used):
    """NOTICE.md for a layer: every source, its publisher, licence and link (and licence texts that must travel)."""
    lines = ["# Sources of this community layer", "",
             "Each source keeps its own licence. Using this layer in your own game is what the sources are published "
             "for. If you republish this data, pass this layer on (also inside an app) or serve it publicly, honour "
             "the licence of every source below: some require credit or that their notice travels with the data.", ""]
    for u in used:
        who = f"rider {u['rider']}, published by github.com/{u['signed_by']}" if u.get("signed_by") else \
            (f"rider {u['rider']} (local folder, publisher not checked)" if u.get("rider") else u.get("attribution") or "")
        lines.append(f"- **{u['id']}** ({u['type']}): {who}; licence **{u.get('license') or 'unknown'}**"
                     + (f"; {u['url']}" if u.get("url") else "") + f"; commit {u['commit'][:12]}")
    for u in used:
        if u.get("license_text"):
            lines += ["", f"## {u['id']}: licence text", "", "```", u["license_text"].rstrip(), "```"]
    open(path, "w").write("\n".join(lines) + "\n")


# ---- install ----

def game_running():
    return subprocess.run(["pgrep", "-x", "TrialsFrontier"], capture_output=True).returncode == 0


def cmd_install(container, layer=None):
    layer = layer or os.path.join(HOME, "layer")
    if not os.path.exists(os.path.join(layer, "community.json")):
        sys.exit(f"no layer at {layer}: run build (or update) first")
    if game_running():
        sys.exit("close the game first (pkill -x TrialsFrontier): the server reads the layer while it runs")
    data = os.path.join(container, "Documents", "LocalServices")
    if not os.path.isdir(data):
        sys.exit(f"{data} not found: start the patched game once first (or pass --container)")
    dest = os.path.join(data, "community")
    tmp, old = dest + ".new", dest + ".old"
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(layer, tmp)
    if os.path.exists(dest):
        os.rename(dest, old)
    os.rename(tmp, dest)
    shutil.rmtree(old, ignore_errors=True)
    print(f"installed into {dest} (used from the next game start)")


def cmd_status():
    print(f"home: {HOME}")
    cmd_list()
    p = os.path.join(HOME, "layer", "community.json")
    if os.path.exists(p):
        layer = json.load(open(p))
        print(f"layer: {len(layer['riders'])} riders, {sum(len(b) for b in layer['results'].values())} results, "
              f"{len(layer['ghosts'])} ghosts from {', '.join(s['id'] for s in layer['sources']) or 'nothing'}")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    container = gb.opt("--container", default=DEFAULT_CONTAINER)
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        if cmd == "list":
            cmd_list()
        elif cmd == "add" and args:
            cmd_add(args[0])
        elif cmd == "remove" and args:
            cmd_remove(args[0])
        elif cmd in ("enable", "disable") and args:
            cmd_enable(args[0], cmd == "enable")
        elif cmd == "discover":
            cmd_discover()
        elif cmd == "sync":
            cmd_sync()
        elif cmd == "build":
            cmd_build(args[0] if args else None)
        elif cmd == "install":
            cmd_install(container)
        elif cmd == "update":
            cmd_sync()
            cmd_build()
            if game_running():
                print("the game is running: run `community.py install` after closing it (pkill -x TrialsFrontier)")
            else:
                cmd_install(container)
        elif cmd == "status":
            cmd_status()
        else:
            sys.exit(__doc__)
    except gb.BundleError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
