"""Share Trials Frontier best times and ghosts as "bundles" (to race other riders' bundles: scripts/community.py).

Usage:
  python3 -I ghost_bundle.py export  <game Documents dir> <bundle dir> [--app <TrialsFrontier.app>] [--avatar <png>]
                                     [--name <rider name>] [--license CC0-1.0|CC-BY-4.0]
                                     [--include-others | --include-others-with-names]
  python3 -I ghost_bundle.py update  <bundle dir> [--documents <dir>] [--dry-run]
  python3 -I ghost_bundle.py check   <bundle dir>
  python3 -I ghost_bundle.py verify  <owner/repo>
  python3 -I ghost_bundle.py publish <bundle dir> [--repo <name>] [--i-agree]
                                     [--dry-run [--preview-dir <dir>]]
  python3 -I ghost_bundle.py search

export   reads the save (player.bin), your ghost files and, if present, the local services store (newer runs from
         the patched game) and writes a bundle: trials-frontier-bundle.json, ghosts/<leaderboard>.bin, README.md,
         LICENSE, avatar.png. Never the save itself (it holds other players' names and ids) and never your profile id:
         only two hashes of it (see docs/BUNDLES.md). --app adds track names from your copy of the game;
         --include-others adds the other riders' ghosts your game downloaded (others/<hash>/), by hash only:
         their names come from their own bundles. --include-others-with-names also adds the names your save has for
         some of them (in-game names as the leaderboards showed them; whether sharing them is acceptable is yours
         to judge). Others' ghosts are only those the original game downloaded: robot opponents the local
         server served later (possibly from other people's bundles) are never re-shared.
update   re-exports a bundle with the options of its first export (kept in the bundle folder's .export.json, never
         published), keeps whatever the bundle already had where it is better (best time and fastest ghost per
         leaderboard), shows the new and better times, and publishes the update (agreement, new commits signed by
         GitHub in the same repository; --dry-run builds the preview instead). Run it whenever you have new best
         times. --documents <dir>: this time from another copy of the same profile, e.g. an iPhone's Documents
         pulled with `scripts/ios_device.py pull-data` (iOS 17+) or copied with Finder (file-sharing build); a
         different profile is refused.
check    validates a bundle the way scripts/community.py does before using it.
verify   checks a published bundle: valid, and every commit made through GitHub by the publisher it names (signed
         by GitHub, shown as Verified).
publish  shows what will be published, asks you to agree, then (GitHub CLI `gh`, logged in to github.com; the
         web login is fine) creates or updates a public repository <you>/trials-frontier-ghosts-<name> with the
         topics that make bundles findable. The files are committed through GitHub's API, so GitHub signs every
         commit for your account: that is the proof the bundle is yours (a future fan server can rely on it), and
         there is no key to keep or lose. The manifest names you as publisher and states that the rider is you.
         --dry-run publishes nothing: it writes the files exactly as they would be published to
         <bundle dir>-preview and prints what would be committed.
search   lists published bundles (GitHub topic trials-frontier-bundle).
"""
import base64
import datetime
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
from datapack import read_file  # noqa: E402
from local_services import decode, game_hash, ghost_drive_time, known_riders, read_scores, save_name  # noqa: E402

FORMAT, FORMAT_VERSION = "trials-frontier-bundle", 1
MANIFEST = "trials-frontier-bundle.json"
STATEMENT = ("The publisher states that the rider is their own and that the rider's times and ghosts were recorded "
             "by them; anything under 'others' was downloaded by their game.")
TOPICS = ["trials-frontier", "trials-frontier-bundle", "trials-frontier-ghosts", "game-preservation"]
PATCH_REPO = "https://github.com/gtjeffw/trials-frontier-patch"
DEFAULT_CONTAINER = os.path.expanduser("~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data")
LICENSES = {
    "CC0-1.0": ("CC0 1.0 Universal (public domain dedication)", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "CC-BY-4.0": ("Creative Commons Attribution 4.0 International", "https://creativecommons.org/licenses/by/4.0/"),
}
MAX_GHOST, MAX_AVATAR, MAX_ENTRIES = 2_000_000, 512_000, 5000


class BundleError(Exception):
    pass


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


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def profile_hashes(pid):
    """(game hash, sha256): the game's 32-bit mt::String::getHashCode, as in robot_ghost-<HASH>-… file names, and a
    sha256 that only someone who already knows the profile id can match."""
    return "%08X" % game_hash(pid), sha256(("trials-frontier-profile:" + pid).encode())


def rider_id(ghash):
    """Store id for a rider known by game hash: the same made-up id the server gives downloaded opponents."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "trials-frontier-robot:" + ghash))


def ghost_bike(data):
    try:
        if struct.unpack_from("<I", data, 0)[0] >= 3:
            return struct.unpack_from("<I", zlib.decompress(data[16:]), 0)[0]
    except (struct.error, zlib.error):
        pass
    return None


def track_names(app):
    """{track id: English name} from the game's own content pack (your copy; names are not stored in this repo)."""
    pack = open(os.path.join(app, "data", "TrialsMobile", "content.dat"), "rb").read()
    levels = json.loads(read_file(pack, game_hash("/conf/levels.txt")))["Levels"]
    d = read_file(pack, game_hash("/gen/lang/english_strings.bin"))
    strings, i = {}, 9
    while i + 6 <= len(d):
        key, length = struct.unpack_from("<IH", d, i)
        strings[key] = d[i + 6:i + 6 + length].rstrip(b"\0").decode("utf-8", "replace")
        i += 6 + length
    return {l["ID"]: strings.get(game_hash(l["N"]), l["N"]) for l in levels}


# ---- export ----

EXPORT_OPTIONS = ".export.json"  # how the bundle was exported (local paths): for `update`, never published


def export(docs, out, app=None, avatar=None, name=None, lic="CC0-1.0", others=False, with_names=False):
    others = others or with_names
    docs, out = os.path.abspath(docs), os.path.abspath(out)
    if lic not in LICENSES:
        sys.exit(f"--license: one of {', '.join(LICENSES)}")
    save = os.path.join(docs, "player.bin")
    if not os.path.exists(save):
        sys.exit(f"no player.bin in {docs}")
    raw = decode(open(save, "rb").read())[1]
    pid = raw[276:276 + 40].split(b"\0")[0].decode("ascii", "replace")
    if not re.fullmatch(r"[0-9a-f-]{36}", pid):
        # a player who was never on Ubisoft: the local server made up a random (version 4) profile id for them
        store_file = os.path.join(docs, "LocalServices", "store.json")
        pid = json.load(open(store_file)).get("new_player_profile", "") if os.path.exists(store_file) else ""
        if not re.fullmatch(r"[0-9a-f-]{36}", pid):
            sys.exit("the save has no profile id and the local server has none either (start the patched game once)")
    name = name or save_name(raw) or "Rider"
    ghash, psha = profile_hashes(pid)
    names = track_names(app) if app else {}

    # best results: the save's table, improved by later runs in the local services store
    best = {lb: {"faults": f, "time_ms": ms, "bike": bike, "source": "save"} for lb, (f, ms, bike) in read_scores(raw).items()}
    store_dir = os.path.join(docs, "LocalServices")
    store = json.load(open(os.path.join(store_dir, "store.json"))) if os.path.exists(os.path.join(store_dir, "store.json")) else None
    if store:
        for board, entries in store["results"].items():
            m, st = re.fullmatch(r"track(\d+)", board), entries.get(pid)
            if m and st and st.get("source") != "save" and st.get("drivetime"):
                new = {"faults": st["data"] & 0xFF, "time_ms": st["drivetime"], "bike": (st["data"] >> 8) & 0x3F,
                       "source": "local-services"}
                old = best.get(int(m.group(1)))
                if not old or (new["faults"], new["time_ms"]) <= (old["faults"], old["time_ms"]):
                    best[int(m.group(1))] = new  # the game also saves it: the store knows it was played later

    # own ghosts: the fastest per leaderboard, from the store (newer) and the save's ghost files
    ghosts = {}
    def offer(lb, data, source):
        ms = ghost_drive_time(data)
        if ms and (lb not in ghosts or ms < ghosts[lb][1] or (ms == ghosts[lb][1] and source == "local-services")):
            ghosts[lb] = (data, ms, source)
    prefix = "ghost_%08x_" % game_hash(pid)
    for f in sorted(os.listdir(docs)):
        m = re.fullmatch(re.escape(prefix) + r"(\d+)\.bin", f)
        if m:
            offer(int(m.group(1)), open(os.path.join(docs, f), "rb").read(), "save")
    if store:
        for cid, g in sorted(store["ghosts"].items()):
            path = os.path.join(store_dir, "ghosts", "%d.bin" % int(cid))
            if g["profile"] == pid and g.get("payload", True) and os.path.exists(path):
                offer(g["track_id"], open(path, "rb").read(), "save" if g.get("source") else "local-services")

    # write the bundle (keeping .git so publish can update an existing repository)
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        if f != ".git":
            p = os.path.join(out, f)
            shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)
    os.makedirs(os.path.join(out, "ghosts"))
    results = []
    for lb in sorted(best):
        r = {"leaderboard": lb, "track": lb & 0xFFFF, **best[lb]}
        if names.get(lb & 0xFFFF):
            r["track_name"] = names[lb & 0xFFFF]
        results.append(r)
    ghost_list = []
    for lb in sorted(ghosts):
        data, ms, source = ghosts[lb]
        rel = f"ghosts/{lb}.bin"
        open(os.path.join(out, rel), "wb").write(data)
        g = {"leaderboard": lb, "track": lb & 0xFFFF, "time_ms": ms, "bike": ghost_bike(data), "file": rel,
             "sha256": sha256(data), "source": source}
        if names.get(lb & 0xFFFF):
            g["track_name"] = names[lb & 0xFFFF]
        ghost_list.append(g)
    rider = {"name": name, "game_hash": ghash, "profile_sha256": psha}
    if avatar:
        png = open(avatar, "rb").read()
        if not png.startswith(b"\x89PNG") or len(png) > MAX_AVATAR:
            sys.exit("--avatar: a PNG under 512 KB (146x146 like the game's)")
        open(os.path.join(out, "avatar.png"), "wb").write(png)
        rider["avatar"] = {"file": "avatar.png", "sha256": sha256(png)}
    manifest = {
        "format": FORMAT, "format_version": FORMAT_VERSION,
        "game": {"name": "Trials Frontier", "version": "7.9.0", "platform": "iOS"},
        "created": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tool": PATCH_REPO + " scripts/ghost_bundle.py",
        "license": lic,
        "rider": rider,
        "results": results,
        "ghosts": ghost_list,
    }
    if others:
        manifest["others"] = export_others(docs, out, ghash, raw if with_names else None, names, store)
    write_text(out, manifest)
    json.dump(manifest, open(os.path.join(out, MANIFEST), "w"), indent=1, ensure_ascii=False)
    json.dump({"documents": docs, "app": app and os.path.abspath(app), "avatar": avatar and os.path.abspath(avatar),
               "name": name if name != save_name(raw) else None,
               "license": lic, "others": bool(others), "with_names": bool(with_names)},
              open(os.path.join(out, EXPORT_OPTIONS), "w"), indent=1)
    n_other = sum(len(o["ghosts"]) for o in manifest.get("others", []))
    print(f"wrote {out}: {name} ({ghash}), {len(results)} best times, {len(ghost_list)} ghosts"
          + (f", {len(manifest['others'])} other riders with {n_other} ghosts" if others else ""))
    check(out)


def export_others(docs, out, own_hash, raw=None, track_names_=None, store=None):
    """Opponent ghosts the game downloaded: robot_ghost-<HASH>-<LBHEX>.robot, by hash; with the save (raw) also the
    names it keeps for some of them, otherwise none (a rider's name is then theirs to publish in their own bundle).
    Only files from the original online game: once the local server runs, the game also saves the robot opponents
    it serves (possibly from other people's bundles), so with a store only the files it imported at its first start
    count (their names are the ghosts' "source")."""
    original = {g.get("source") for g in store["ghosts"].values()} if store else None
    named = {"%08X" % game_hash(p): n for p, n in known_riders(raw).items()
             if not re.fullmatch(r"(?i)rider( [0-9A-F]{8})?", n)} if raw else {}  # not the local server's placeholders
    riders = {}
    for f in sorted(os.listdir(docs)):
        m = re.fullmatch(r"robot_ghost-([0-9A-F]+)-([0-9A-F]+)\.robot", f)
        if not m or (original is not None and f not in original):
            continue
        h, lb = m.group(1).zfill(8), int(m.group(2), 16)
        data = open(os.path.join(docs, f), "rb").read()
        ms = ghost_drive_time(data)
        if not ms or h == own_hash:
            continue
        rel = f"others/{h}/{lb}.bin"
        os.makedirs(os.path.join(out, "others", h), exist_ok=True)
        open(os.path.join(out, rel), "wb").write(data)
        r = riders.setdefault(h, {"game_hash": h, "ghosts": []})
        if h in named:
            r["name"] = named[h]
        g = {"leaderboard": lb, "track": lb & 0xFFFF, "time_ms": ms, "bike": ghost_bike(data), "file": rel,
             "sha256": sha256(data), "source": "downloaded-opponent"}
        if (track_names_ or {}).get(lb & 0xFFFF):
            g["track_name"] = track_names_[lb & 0xFFFF]
        r["ghosts"].append(g)
    return [riders[h] for h in sorted(riders)]


def write_text(out, m, repo=None):
    r, lic = m["rider"], LICENSES[m["license"]]
    others = m.get("others")
    lines = [
        f"# Trials Frontier ghosts: {r['name']}",
        "",
        f"Best times and ghost replays of **{r['name']}** in Trials Frontier {m['game']['version']} (RedLynx/Ubisoft, "
        f"{m['game']['platform']}), whose online services have ended. A `{FORMAT}` (format {m['format_version']}), "
        f"made with [trials-frontier-patch]({PATCH_REPO}).",
    ]
    if m.get("publisher"):
        lines += ["", f"Published by [github.com/{m['publisher']['github']}](https://github.com/{m['publisher']['github']}), "
                  f"who states that **{r['name']}** is their own rider and these are their own runs. Every commit here "
                  "was made through GitHub by that account and signed by GitHub (shown as Verified); check it with "
                  f"`python3 -I scripts/ghost_bundle.py verify {repo or '<owner>/<repository>'}`."]
    lines += [
        "",
        f"- {len(m['results'])} best times, {len(m['ghosts'])} ghosts (`ghosts/<leaderboard>.bin`, the game's own "
        "ghost files)",
        f"- rider hash `{r['game_hash']}` (the game's hash of the profile id; downloaded-opponent files are named after "
        "it), profile sha256 in the manifest",
    ]
    if others:
        lines.append(f"- {len(others)} other riders' ghosts that the game downloaded as opponents (`others/<hash>/`)")
    lines += [
        "",
        "## Use",
        "",
        "Race these ghosts in a game patched with trials-frontier-patch (local services): in the patch repository's "
        "folder, with the game closed, add this bundle to your sources and update (later updates of the bundle "
        "arrive the same way):",
        "",
        "```",
        f"python3 -I scripts/community.py add {repo or '<owner>/<repository>'}",
        "python3 -I scripts/community.py update",
        "```",
        "",
        "Everything is described in `trials-frontier-bundle.json`; the format is documented in the patch repository "
        "(`docs/BUNDLES.md`). `source` says where each entry came from: `save` (the game's save when exported: the years "
        "of online play, possibly also offline play since), `local-services` (played later in a patched game with "
        "local services), "
        "`downloaded-opponent` (another rider's ghost the game downloaded).",
        "",
        "## Licence",
        "",
        f"The publisher releases this data under [{lic[0]}]({lic[1]}) (`{m['license']}`). Trials Frontier itself belongs "
        "to Ubisoft/RedLynx; no game files are included.",
        "",
    ]
    open(os.path.join(out, "README.md"), "w").write("\n".join(lines))
    open(os.path.join(out, "LICENSE"), "w").write(
        f"The data in this repository (times, ghost replays, avatar) is released under {lic[0]}.\n"
        f"SPDX-License-Identifier: {m['license']}\n{lic[1]}\n")


# ---- check ----

def check(bundle):
    """Validate a bundle (untrusted input: anything else is refused). Returns the manifest."""
    def fail(msg):
        raise BundleError(f"not a valid bundle ({bundle}): {msg}")
    real = os.path.realpath(bundle)
    path = os.path.join(real, MANIFEST)
    if not os.path.isfile(path) or os.path.islink(path) or os.path.getsize(path) > 20_000_000:
        fail(f"no {MANIFEST}")
    try:
        m = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        fail(f"manifest is not JSON ({e})")
    if not isinstance(m, dict) or m.get("format") != FORMAT:
        fail("wrong format")
    if m.get("format_version") != FORMAT_VERSION:
        fail(f"format version {m.get('format_version')} (this tool reads {FORMAT_VERSION}; update trials-frontier-patch)")

    def is_int(v, lo, hi):
        return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi

    def name_ok(v):
        return isinstance(v, str) and 1 <= len(v) <= 64 and v.isprintable()

    def read(rel, pattern, limit):
        if not isinstance(rel, str) or not re.fullmatch(pattern, rel):
            fail(f"bad file name {rel!r}")
        p = os.path.join(real, rel)
        if os.path.islink(p) or not os.path.isfile(p) or not os.path.realpath(p).startswith(real + os.sep):
            fail(f"{rel} missing or not a plain file")
        if os.path.getsize(p) > limit:
            fail(f"{rel} too large")
        return open(p, "rb").read()

    def ghosts_ok(entries, pattern):
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            fail("ghost list")
        seen = set()
        for g in entries:
            if not isinstance(g, dict) or not is_int(g.get("leaderboard"), 0, 0xFFFFFFFF) or g["leaderboard"] in seen:
                fail(f"ghost entry {g!r:.80}")
            seen.add(g["leaderboard"])
            data = read(g.get("file"), pattern % g["leaderboard"], MAX_GHOST)
            if sha256(data) != g.get("sha256"):
                fail(f"{g['file']}: sha256 differs")
            if ghost_drive_time(data) != g.get("time_ms") or not is_int(g.get("time_ms"), 1, 3_600_000):
                fail(f"{g['file']}: not a ghost of the stated time")

    r = m.get("rider")
    if not isinstance(r, dict) or not name_ok(r.get("name")) or not re.fullmatch(r"[0-9A-F]{8}", str(r.get("game_hash"))) \
            or not re.fullmatch(r"[0-9a-f]{64}", str(r.get("profile_sha256"))):
        fail("rider")
    if "avatar" in r:
        png = read(r["avatar"].get("file") if isinstance(r["avatar"], dict) else None, r"avatar\.png", MAX_AVATAR)
        if not png.startswith(b"\x89PNG") or sha256(png) != r["avatar"].get("sha256"):
            fail("avatar")
    results = m.get("results")
    if not isinstance(results, list) or len(results) > MAX_ENTRIES:
        fail("results")
    for e in results:
        if not isinstance(e, dict) or not is_int(e.get("leaderboard"), 0, 0xFFFFFFFF) or \
                not is_int(e.get("time_ms"), 1, 3_600_000) or not is_int(e.get("faults"), 0, 255) or \
                not is_int(e.get("bike") or 0, 0, 63):
            fail(f"result {e!r:.80}")
    ghosts_ok(m.get("ghosts"), r"ghosts/%d\.bin")
    others = m.get("others", [])
    if not isinstance(others, list) or len(others) > MAX_ENTRIES:
        fail("others")
    for o in others:
        if not isinstance(o, dict) or not re.fullmatch(r"[0-9A-F]{8}", str(o.get("game_hash"))) or \
                ("name" in o and not name_ok(o["name"])):
            fail(f"other rider {o!r:.80}")
        ghosts_ok(o.get("ghosts"), "others/" + o["game_hash"] + r"/%d\.bin")
    if m.get("license") not in LICENSES:
        fail("license")
    pub = m.get("publisher")
    if pub is not None and (not isinstance(pub, dict) or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", str(pub.get("github")))
                            or not isinstance(pub.get("statement", ""), str)):
        fail("publisher")
    return m


# ---- GitHub: API calls, verification ----

def gh_ready():
    return shutil.which("gh") is not None and subprocess.run(["gh", "auth", "status", "-h", "github.com"],
                                                             capture_output=True).returncode == 0


def github_get(path):
    """GET a GitHub REST path: through `gh` when logged in (higher rate limit), else the public API."""
    if gh_ready():
        r = subprocess.run(["gh", "api", "-H", "Accept: application/vnd.github+json", path], capture_output=True, text=True)
        if r.returncode != 0:
            raise BundleError(f"GitHub: {path}: {(r.stderr or r.stdout).strip()[:200]}")
        return json.loads(r.stdout)
    try:
        with urllib.request.urlopen(f"https://api.github.com/{path}", timeout=30) as r:
            return json.load(r)
    except (OSError, ValueError) as e:
        raise BundleError(f"GitHub: {path}: {e}")


def verify_repo(full, publisher, head=None):
    """A bundle repository is the publisher's if every commit was made through GitHub by that account: signed by
    GitHub (committer web-flow, verification valid) with the publisher as author. head: the commit that was
    fetched, which must be the newest one. Returns the publisher; BundleError otherwise."""
    commits = github_get(f"repos/{full}/commits?per_page=100")
    if not commits:
        raise BundleError(f"{full}: no commits")
    if head and commits[0]["sha"] != head:
        raise BundleError(f"{full}: changed while fetching (try again)")
    for c in commits:
        v = c["commit"].get("verification") or {}
        author = (c.get("author") or {}).get("login")
        committer = (c.get("committer") or {}).get("login")
        if not (v.get("verified") and v.get("reason") == "valid" and committer == "web-flow"):
            raise BundleError(f"{full}: commit {c['sha'][:10]} is not signed by GitHub ({v.get('reason')})")
        if (author or "").lower() != publisher.lower():
            raise BundleError(f"{full}: commit {c['sha'][:10]} is by {author}, not the publisher {publisher}")
    return publisher


def git_blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ---- publish ----

def run(cmd, cwd=None, dry=False, check_=True):
    print("+ " + " ".join(cmd))
    if dry:
        return ""
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check_ and r.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd[:3])}\n{r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


CONSENT = """By publishing you confirm that:
  - the times and ghosts listed as yours were recorded by you, in your own game, and you have the right to share
    them and release them under {license};
{others}  - you understand this is PUBLIC and lasting: anyone can copy, archive and redistribute it, and deleting
    the repository later will not remove copies.
The bundle contains your rider name "{name}", two hashes of your profile id, your best times and ghost replays{avatar}.
It does not contain your save, your profile id, or any game files."""

OTHERS = """  - this bundle ALSO contains {n} other riders' ghosts that your game downloaded as opponents{names}; you
    take responsibility for sharing them;
"""


def names_note(others):
    named = [o["name"] for o in others if o.get("name")]
    if not named:
        return " (by hash only, no names)"
    return f",\n    {len(named)} of them WITH their in-game names ({', '.join(named[:5])}{', …' if len(named) > 5 else ''})"


def gh(*args, input_=None, dry=False):
    print("+ gh " + " ".join(a if len(a) < 80 else a[:77] + "..." for a in args))
    if dry:
        return ""
    r = subprocess.run(["gh"] + list(args), input=input_, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"gh {args[0]} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def publish(bundle):
    repo, agreed = opt("--repo"), opt("--i-agree", True)
    dry, preview = opt("--dry-run", True), opt("--preview-dir")
    m = check(bundle)
    logged_in = gh_ready()
    if logged_in:
        user = json.loads(gh("api", "user"))
        login = user["login"]
    elif dry:
        login = "YOUR-GITHUB-NAME"
    else:
        sys.exit("needs the GitHub CLI, logged in: brew install gh, then gh auth login (web login is fine)")
    slug = re.sub(r"[^a-z0-9]+", "-", m["rider"]["name"].lower()).strip("-") or m["rider"]["game_hash"].lower()
    repo = repo or f"trials-frontier-ghosts-{slug}"
    full = f"{login}/{repo}"
    others = m.get("others", [])
    print(f"\n{'PREVIEW of publishing' if dry else 'Publish'} {bundle} as https://github.com/{full} (public)\n")
    print(CONSENT.format(license=m["license"], name=m["rider"]["name"],
                         avatar=" and avatar" if "avatar" in m["rider"] else "",
                         others=OTHERS.format(n=len(others), names=names_note(others)) if others else ""))
    if not dry and not agreed and input('\nType "I agree" to publish: ').strip().lower() != "i agree":
        sys.exit("not published")

    # the files exactly as published: the bundle plus the publisher, never the local export options
    m["publisher"] = {"github": login, "statement": STATEMENT}
    target = os.path.abspath(preview or bundle.rstrip("/") + "-preview") if dry else tempfile.mkdtemp(prefix="tf-publish-")
    if dry and os.path.exists(target):
        if not os.path.exists(os.path.join(target, ".trials-frontier-preview")):
            sys.exit(f"{target} exists and is not an earlier preview; choose --preview-dir")
        shutil.rmtree(target)
    shutil.copytree(bundle, target, ignore=shutil.ignore_patterns(".git", EXPORT_OPTIONS, "*.sig"),
                    dirs_exist_ok=not dry)
    json.dump(m, open(os.path.join(target, MANIFEST), "w"), indent=1, ensure_ascii=False)
    write_text(target, m, full)
    check(target)
    files = {}
    for root, _, names in os.walk(target):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), target)
            if rel != ".trials-frontier-preview":
                files[rel] = open(os.path.join(root, n), "rb").read()

    desc = (f"Trials Frontier (iOS) best times and ghosts of {m['rider']['name']} "
            f"- {FORMAT} v{FORMAT_VERSION}, rider {m['rider']['game_hash']}")
    exists = logged_in and subprocess.run(["gh", "repo", "view", full], capture_output=True).returncode == 0
    remote = {}
    if exists:
        info = json.loads(gh("api", f"repos/{full}"))
        branch = info["default_branch"]
        tree = json.loads(gh("api", f"repos/{full}/git/trees/{branch}?recursive=1"))
        remote = {t["path"]: t["sha"] for t in tree.get("tree", []) if t["type"] == "blob"}
    additions = {p: d for p, d in files.items() if remote.get(p) != git_blob_sha(d)}
    deletions = sorted(set(remote) - set(files))
    # commits of at most ~1.5 MB each; the manifest and README come last, so a bundle is complete when they change
    order = sorted(additions, key=lambda p: (p in (MANIFEST, "README.md", "LICENSE"), p))
    batches, cur, size = [], [], 0
    for p in order:
        n = len(additions[p]) * 4 // 3 + 64
        if cur and (size + n > 1_500_000 or len(cur) >= 300):
            batches.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += n
    if cur:
        batches.append(cur)
    print(f"\n{len(additions)} files to add or change, {len(deletions)} to delete, in {len(batches)} commit(s) "
          f"signed by GitHub")
    if dry:
        open(os.path.join(target, ".trials-frontier-preview"), "w").write("made by ghost_bundle.py publish --dry-run\n")
        print(f"\nPreview (nothing was published; {bundle} is unchanged): {target}\n"
              f"  {len(files)} files, {sum(len(d) for d in files.values()) // 1024} KB\n"
              f"  description: {desc}\n  topics: {', '.join(TOPICS)}\n"
              "  every commit is made through GitHub's API, so GitHub signs it (Verified) and no key is needed")
        return
    try:
        if not exists:   # GitHub makes the first commit (its README), signed like the others
            gh("repo", "create", full, "--public", "--description", desc, "--add-readme")
            branch = json.loads(gh("api", f"repos/{full}"))["default_branch"]
        else:
            gh("repo", "edit", full, "--description", desc)
        head = None
        for _ in range(10):   # a new repository's branch can take a moment to appear
            r = subprocess.run(["gh", "api", f"repos/{full}/git/ref/heads/{branch}", "--jq", ".object.sha"],
                               capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                head = r.stdout.strip()
                break
            time.sleep(2)
        if not head:
            sys.exit(f"{full}: branch {branch} not found")
        mutation = ("mutation($input: CreateCommitOnBranchInput!) { createCommitOnBranch(input: $input) "
                    "{ commit { oid url } } }")
        title = f"Trials Frontier ghosts of {m['rider']['name']} ({m['created']})"
        for i, batch in enumerate(batches or [[]]):
            changes = {"additions": [{"path": p, "contents": base64.b64encode(additions[p]).decode()} for p in batch]}
            if i == len(batches or [[]]) - 1 and deletions:
                changes["deletions"] = [{"path": p} for p in deletions]
            if not changes["additions"] and not changes.get("deletions"):
                break
            body = {"query": mutation, "variables": {"input": {
                "branch": {"repositoryNameWithOwner": full, "branchName": branch}, "expectedHeadOid": head,
                "message": {"headline": title + (f" [{i + 1}/{len(batches)}]" if len(batches) > 1 else "")},
                "fileChanges": changes}}}
            out = json.loads(gh("api", "graphql", "--input", "-", input_=json.dumps(body)))
            if out.get("errors"):
                sys.exit(f"GitHub refused the commit: {out['errors'][0].get('message')}")
            head = out["data"]["createCommitOnBranch"]["commit"]["oid"]
        gh("repo", "edit", full, *[a for t in TOPICS for a in ("--add-topic", t)])
    finally:
        shutil.rmtree(target, ignore_errors=True)
    verify_repo(full, login, head)
    print(f"published: https://github.com/{full} (every commit signed by GitHub for {login})")


def merge_previous(bundle, prev_dir, before):
    """Keep what was published before (prev_dir: a copy of the bundle before re-export) where it is better: the best
    result and the fastest ghost per leaderboard, for the rider and for others, so updates from different devices
    (PlayCover, iPhone, iPad) only ever add or improve. Returns the merged manifest."""
    path = os.path.join(bundle, MANIFEST)
    m = json.load(open(path))
    if not before:
        return m
    if before["rider"]["game_hash"] != m["rider"]["game_hash"]:
        raise BundleError(f"this save is a different rider ({m['rider']['name']}, {m['rider']['game_hash']}) than the "
                          f"bundle's ({before['rider']['name']}, {before['rider']['game_hash']}); not merged")
    key = lambda e: (e["faults"], e["time_ms"])
    res = {e["leaderboard"]: e for e in m["results"]}
    for e in before["results"]:
        if e["leaderboard"] not in res or key(e) < key(res[e["leaderboard"]]):
            res[e["leaderboard"]] = e
    m["results"] = [res[k] for k in sorted(res)]

    def keep_faster(new_list, old_list):
        cur = {g["leaderboard"]: g for g in new_list}
        for g in old_list:
            if g["leaderboard"] not in cur or g["time_ms"] < cur[g["leaderboard"]]["time_ms"]:
                dst = os.path.join(bundle, g["file"])
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(os.path.join(prev_dir, g["file"]), dst)
                cur[g["leaderboard"]] = g
        return [cur[k] for k in sorted(cur)]

    m["ghosts"] = keep_faster(m["ghosts"], before["ghosts"])
    if "others" in m or "others" in before:
        others = {o["game_hash"]: o for o in m.get("others", [])}
        for o in before.get("others", []):
            n = others.setdefault(o["game_hash"], {"game_hash": o["game_hash"], "ghosts": []})
            if o.get("name") and not n.get("name"):
                n["name"] = o["name"]
            n["ghosts"] = keep_faster(n["ghosts"], o["ghosts"])
        m["others"] = [others[h] for h in sorted(others)]
    if "avatar" not in m["rider"] and "avatar" in before["rider"]:
        shutil.copyfile(os.path.join(prev_dir, before["rider"]["avatar"]["file"]), os.path.join(bundle, "avatar.png"))
        m["rider"]["avatar"] = before["rider"]["avatar"]
    json.dump(m, open(path, "w"), indent=1, ensure_ascii=False)
    write_text(bundle, m)
    return m


def update(bundle):
    """Re-export (the first export's options, or --documents <dir> for another copy of the same profile, e.g. pulled
    from an iPhone), merge with what the bundle had (best per leaderboard), show the changes, then publish."""
    documents = opt("--documents")
    o_path = os.path.join(bundle, EXPORT_OPTIONS)
    if not os.path.exists(o_path):
        sys.exit(f"{bundle} has no {EXPORT_OPTIONS}: export it once with ghost_bundle.py export")
    o = json.load(open(o_path))
    before = json.load(open(os.path.join(bundle, MANIFEST))) if os.path.exists(os.path.join(bundle, MANIFEST)) else {}
    prev = tempfile.mkdtemp(prefix="tf-bundle-prev-")
    try:
        shutil.copytree(bundle, os.path.join(prev, "b"), ignore=shutil.ignore_patterns(".git"))
        prev_dir = os.path.join(prev, "b")
        try:
            export(documents or o["documents"], bundle, app=o.get("app"), avatar=o.get("avatar"), name=o.get("name"),
                   lic=o.get("license", "CC0-1.0"), others=o.get("others"), with_names=o.get("with_names"))
            if documents:  # export recorded the other folder; keep the original as the default
                json.dump(dict(json.load(open(o_path)), documents=o["documents"]), open(o_path, "w"), indent=1)
            after = merge_previous(bundle, prev_dir, before)
            check(bundle)
        except BaseException:  # any failure (also sys.exit inside export): the bundle stays as it was
            for f in os.listdir(bundle):  # put the previous bundle back
                if f != ".git":
                    p = os.path.join(bundle, f)
                    shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
            shutil.copytree(prev_dir, bundle, dirs_exist_ok=True)
            raise
    finally:
        shutil.rmtree(prev, ignore_errors=True)
    key = lambda e: (e["faults"], e["time_ms"])
    old_res = {e["leaderboard"]: e for e in before.get("results", [])}
    new_res = [e for e in after["results"] if e["leaderboard"] not in old_res]
    better = [e for e in after["results"] if e["leaderboard"] in old_res and key(e) < key(old_res[e["leaderboard"]])]
    old_gh = {g["leaderboard"]: g["sha256"] for g in before.get("ghosts", [])}
    changed = [g for g in after["ghosts"] if old_gh.get(g["leaderboard"]) != g["sha256"]]
    print(f"since the last export: {len(new_res)} new and {len(better)} better times, {len(changed)} new or changed ghosts")
    for e in (new_res + better)[:20]:
        print(f"  {e.get('track_name') or 'track %d' % e['track']:30} {e['faults']}F {e['time_ms'] / 1000:.3f} s"
              + (" (new)" if e in new_res else f" (was {old_res[e['leaderboard']]['time_ms'] / 1000:.3f} s)"))
    if not (new_res or better or changed or "--dry-run" in sys.argv):
        print("nothing new to publish")
        return
    publish(bundle)


def search():
    if shutil.which("gh") is None:
        sys.exit("needs the GitHub CLI (brew install gh)")
    out = subprocess.run(["gh", "search", "repos", "--topic", "trials-frontier-bundle", "--limit", "200",
                          "--json", "fullName,description,updatedAt"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(out.stderr.strip())
    for r in sorted(json.loads(out.stdout), key=lambda r: r["fullName"].lower()):
        print(f"{r['fullName']:50} {r['updatedAt'][:10]}  {r['description'] or ''}")


def main():
    try:
        cli()
    except BundleError as e:
        sys.exit(str(e))


def cli():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "export" and len(sys.argv) >= 4:
        export(sys.argv[2], sys.argv[3], app=opt("--app"), avatar=opt("--avatar"), name=opt("--name"),
               lic=opt("--license", default="CC0-1.0"), others=opt("--include-others", True),
               with_names=opt("--include-others-with-names", True))
    elif cmd == "update" and len(sys.argv) >= 3:
        update(sys.argv[2])
    elif cmd == "verify" and len(sys.argv) >= 3:
        full = sys.argv[2].removeprefix("https://github.com/").strip("/").removesuffix(".git")
        tmp = tempfile.mkdtemp(prefix="tf-verify-")
        try:
            r = subprocess.run(["git", "clone", "-q", "--depth", "1", "-c", "core.symlinks=false",
                                f"https://github.com/{full}.git", tmp], capture_output=True, text=True)
            if r.returncode != 0:
                sys.exit(f"could not fetch {full}: {r.stderr.strip()[:200]}")
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp, capture_output=True, text=True).stdout.strip()
            m = check(tmp)
            login = (m.get("publisher") or {}).get("github")
            if not login:
                sys.exit(f"{full}: the manifest names no publisher")
            verify_repo(full, login, head)
            print(f"ok: {full} is {m['rider']['name']}'s bundle, every commit signed by GitHub for {login}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    elif cmd == "check" and len(sys.argv) >= 3:
        m = check(sys.argv[2])
        print(f"ok: {m['rider']['name']} ({m['rider']['game_hash']}), {len(m['results'])} times, {len(m['ghosts'])} ghosts,"
              f" {len(m.get('others', []))} other riders")
    elif cmd == "publish" and len(sys.argv) >= 3:
        publish(sys.argv[2])
    elif cmd == "search":
        search()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
