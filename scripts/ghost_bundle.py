"""Share Trials Frontier best times and ghosts as "bundles", and race other riders' bundles in your patched game.

Usage:
  python3 -I ghost_bundle.py export  <game Documents dir> <bundle dir> [--app <TrialsFrontier.app>] [--avatar <png>]
                                     [--name <rider name>] [--license CC0-1.0|CC-BY-4.0]
                                     [--include-others | --include-others-with-names]
  python3 -I ghost_bundle.py check   <bundle dir> [--verify]
  python3 -I ghost_bundle.py publish <bundle dir> [--repo <name>] [--sign-key <ssh private key>] [--i-agree] [--dry-run]
  python3 -I ghost_bundle.py import  <bundle dir | https://github.com/<owner>/<repo> | <owner>/<repo>>
                                     [--container <game data dir>]
  python3 -I ghost_bundle.py search

export   reads the save (player.bin), your ghost files and, if present, the local services store (newer runs from
         the patched game) and writes a bundle: trials-frontier-bundle.json, ghosts/<leaderboard>.bin, README.md,
         LICENSE, avatar.png. Never the save itself (it holds other players' names and ids) and never your profile id:
         only two hashes of it (see docs/BUNDLES.md). --app adds track names from your copy of the game;
         --include-others adds the other riders' ghosts your game downloaded (others/<hash>/), by hash only:
         their names come from their own bundles. --include-others-with-names also adds the names your save has for
         some of them (in-game names as the leaderboards showed them; whether sharing them is acceptable is yours
         to judge). Re-exporting into the same folder keeps its git history (for publish updates).
check    validates a bundle the way import does; --verify also checks the manifest signature against the
         publisher's SSH keys on GitHub.
publish  shows what will be published, asks you to agree, then (GitHub CLI `gh`, logged in) creates or updates a
         public repository <you>/trials-frontier-ghosts-<name> with the topics that make bundles findable. Commits
         use your GitHub noreply address. --sign-key signs the manifest with an SSH key you have on GitHub.
import   adds a bundle's riders, times and ghosts to the patched game's store (close the game first). Riders are
         keyed by the game's own hash of their profile id, so they merge with the "Rider <hash>" opponents your game
         downloaded back then. Default container: PlayCover's (com.ubisoft.redlynx.trialsfrontier).
search   lists published bundles (GitHub topic trials-frontier-bundle).
"""
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
import urllib.request
import uuid
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "server"))
from datapack import read_file  # noqa: E402
from local_services import decode, game_hash, ghost_drive_time, known_riders, read_scores  # noqa: E402

FORMAT, FORMAT_VERSION = "trials-frontier-bundle", 1
MANIFEST, SIGNATURE = "trials-frontier-bundle.json", "trials-frontier-bundle.json.sig"
SIGN_NAMESPACE = "trials-frontier-bundle"
TOPICS = ["trials-frontier", "trials-frontier-bundle", "trials-frontier-ghosts", "game-preservation"]
PATCH_REPO = "https://github.com/gtjeffw/trials-frontier-patch"
DEFAULT_CONTAINER = os.path.expanduser("~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data")
LICENSES = {
    "CC0-1.0": ("CC0 1.0 Universal (public domain dedication)", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "CC-BY-4.0": ("Creative Commons Attribution 4.0 International", "https://creativecommons.org/licenses/by/4.0/"),
}
MAX_GHOST, MAX_AVATAR, MAX_ENTRIES = 2_000_000, 512_000, 5000


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

def export(docs, out):
    app, avatar, name, lic = opt("--app"), opt("--avatar"), opt("--name"), opt("--license", default="CC0-1.0")
    with_names = opt("--include-others-with-names", True)
    others = opt("--include-others", True) or with_names
    if lic not in LICENSES:
        sys.exit(f"--license: one of {', '.join(LICENSES)}")
    save = os.path.join(docs, "player.bin")
    if not os.path.exists(save):
        sys.exit(f"no player.bin in {docs}")
    raw = decode(open(save, "rb").read())[1]
    pid = raw[276:276 + 40].split(b"\0")[0].decode("ascii", "replace")
    if not re.fullmatch(r"[0-9a-f-]{36}", pid):
        sys.exit("the save has no profile id (a new player who never logged in has nothing to share yet)")
    name = name or raw[20:20 + 128].split(b"\0")[0].decode("utf-8", "replace") or "Rider"
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
        manifest["others"] = export_others(docs, out, ghash, raw if with_names else None)
    write_text(out, manifest)
    json.dump(manifest, open(os.path.join(out, MANIFEST), "w"), indent=1, ensure_ascii=False)
    n_other = sum(len(o["ghosts"]) for o in manifest.get("others", []))
    print(f"wrote {out}: {name} ({ghash}), {len(results)} best times, {len(ghost_list)} ghosts"
          + (f", {len(manifest['others'])} other riders with {n_other} ghosts" if others else ""))
    check(out)


def export_others(docs, out, own_hash, raw=None):
    """Opponent ghosts the game downloaded: robot_ghost-<HASH>-<LBHEX>.robot, by hash; with the save (raw) also the
    names it keeps for some of them, otherwise none (a rider's name is then theirs to publish in their own bundle)."""
    named = {"%08X" % game_hash(p): n for p, n in known_riders(raw).items()
             if not re.fullmatch(r"(?i)rider( [0-9A-F]{8})?", n)} if raw else {}  # not the local server's placeholders
    riders = {}
    for f in sorted(os.listdir(docs)):
        m = re.fullmatch(r"robot_ghost-([0-9A-F]+)-([0-9A-F]+)\.robot", f)
        if not m:
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
        r["ghosts"].append({"leaderboard": lb, "track": lb & 0xFFFF, "time_ms": ms, "bike": ghost_bike(data),
                            "file": rel, "sha256": sha256(data), "source": "downloaded-opponent"})
    return [riders[h] for h in sorted(riders)]


def write_text(out, m):
    r, lic = m["rider"], LICENSES[m["license"]]
    others = m.get("others")
    lines = [
        f"# Trials Frontier ghosts: {r['name']}",
        "",
        f"Best times and ghost replays of **{r['name']}** in Trials Frontier {m['game']['version']} (RedLynx/Ubisoft, "
        f"{m['game']['platform']}), whose online services have ended. A `{FORMAT}` (format {m['format_version']}), "
        f"made with [trials-frontier-patch]({PATCH_REPO}).",
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
        "Race these ghosts in a patched game built with trials-frontier-patch (local services):",
        "",
        "```",
        "python3 -I scripts/ghost_bundle.py import <this repository's URL>",
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
        f"The publisher releases this data under {lic[0]} ({m['license']}, {lic[1]}). Trials Frontier itself belongs "
        "to Ubisoft/RedLynx; no game files are included.",
        "",
    ]
    open(os.path.join(out, "README.md"), "w").write("\n".join(lines))
    open(os.path.join(out, "LICENSE"), "w").write(
        f"The data in this repository (times, ghost replays, avatar) is released under {lic[0]}.\n"
        f"SPDX-License-Identifier: {m['license']}\n{lic[1]}\n")


# ---- check ----

def check(bundle, verify=False):
    """Validate a bundle (untrusted input: anything else is refused). Returns the manifest."""
    def fail(msg):
        sys.exit(f"not a valid bundle ({bundle}): {msg}")
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
    if verify:
        verify_signature(real, m)
    return m


def verify_signature(bundle, m):
    login = (m.get("publisher") or {}).get("github")
    sig = os.path.join(bundle, SIGNATURE)
    if not login or not os.path.isfile(sig):
        sys.exit("not signed (no publisher or no signature)")
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", login):
        sys.exit("bad publisher name")
    keys = urllib.request.urlopen(f"https://github.com/{login}.keys", timeout=20).read().decode().split("\n")
    with tempfile.NamedTemporaryFile("w", suffix=".signers", delete=False) as fh:
        fh.write("".join(f"{login} {k}\n" for k in keys if k.strip()))
    try:
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", fh.name, "-I", login, "-n", SIGN_NAMESPACE, "-s", sig],
                           stdin=open(os.path.join(bundle, MANIFEST), "rb"), capture_output=True, text=True)
    finally:
        os.remove(fh.name)
    if r.returncode != 0:
        sys.exit(f"signature does NOT match {login}'s SSH keys on GitHub: {r.stderr.strip() or r.stdout.strip()}")
    print(f"signature ok: signed by an SSH key of github.com/{login}")


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


def publish(bundle):
    repo, key, agreed, dry = opt("--repo"), opt("--sign-key"), opt("--i-agree", True), opt("--dry-run", True)
    m = check(bundle)
    if shutil.which("gh") is None:
        sys.exit("needs the GitHub CLI: brew install gh, then gh auth login")
    if subprocess.run(["gh", "auth", "status"], capture_output=True).returncode != 0:
        sys.exit("not logged in to GitHub: gh auth login")
    user = json.loads(run(["gh", "api", "user"]))
    login, uid = user["login"], user["id"]
    slug = re.sub(r"[^a-z0-9]+", "-", m["rider"]["name"].lower()).strip("-") or m["rider"]["game_hash"].lower()
    repo = repo or f"trials-frontier-ghosts-{slug}"
    full = f"{login}/{repo}"
    others = m.get("others", [])
    print(f"\nPublish {bundle} as https://github.com/{full} (public)\n")
    print(CONSENT.format(license=m["license"], name=m["rider"]["name"],
                         avatar=" and avatar" if "avatar" in m["rider"] else "",
                         others=OTHERS.format(n=len(others), names=names_note(others)) if others else ""))
    if not agreed:
        if input('\nType "I agree" to publish: ').strip().lower() != "i agree":
            sys.exit("not published")

    m["publisher"] = {"github": login}
    json.dump(m, open(os.path.join(bundle, MANIFEST), "w"), indent=1, ensure_ascii=False)
    sig = os.path.join(bundle, SIGNATURE)
    if os.path.exists(sig):
        os.remove(sig)
    if key:
        run(["ssh-keygen", "-Y", "sign", "-f", key, "-n", SIGN_NAMESPACE, os.path.join(bundle, MANIFEST)], dry=dry)

    noreply = f"{uid}+{login}@users.noreply.github.com"
    if not os.path.isdir(os.path.join(bundle, ".git")):
        run(["git", "init", "-q", "-b", "main"], cwd=bundle, dry=dry)
    run(["git", "config", "user.name", login], cwd=bundle, dry=dry)
    run(["git", "config", "user.email", noreply], cwd=bundle, dry=dry)  # never your private email
    run(["git", "add", "-A"], cwd=bundle, dry=dry)
    if dry or subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=bundle).returncode != 0:
        run(["git", "commit", "-q", "-m", f"Trials Frontier ghosts of {m['rider']['name']} ({m['created']})"],
            cwd=bundle, dry=dry)
    desc = (f"Trials Frontier (iOS) best times and ghosts of {m['rider']['name']} "
            f"- {FORMAT} v{FORMAT_VERSION}, rider {m['rider']['game_hash']}")
    exists = subprocess.run(["gh", "repo", "view", full], capture_output=True).returncode == 0
    if exists:
        remotes = run(["git", "remote"], cwd=bundle, dry=dry)
        if "origin" not in remotes.split():
            run(["git", "remote", "add", "origin", f"https://github.com/{full}.git"], cwd=bundle, dry=dry)
        run(["git", "push", "-u", "origin", "main"], cwd=bundle, dry=dry)
        run(["gh", "repo", "edit", full, "--description", desc], dry=dry)
    else:
        run(["gh", "repo", "create", full, "--public", "--description", desc, "--source", bundle, "--remote",
             "origin", "--push"], dry=dry)
    run(["gh", "repo", "edit", full] + [a for t in TOPICS for a in ("--add-topic", t)], dry=dry)
    print(f"{'(dry run) ' if dry else ''}published: https://github.com/{full}")


# ---- import ----

def fetch(src):
    """A local bundle folder, or a GitHub repository cloned (shallow) into a temporary folder."""
    if os.path.isdir(src):
        return src, None, os.path.abspath(src)
    m = re.fullmatch(r"(?:https://github\.com/)?([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?", src)
    if not m:
        sys.exit(f"{src}: not a folder or a GitHub repository")
    tmp = tempfile.mkdtemp(prefix="tf-bundle-")
    url = f"https://github.com/{m.group(1)}/{m.group(2)}.git"
    r = subprocess.run(["git", "clone", "-q", "--depth", "1", "-c", "core.symlinks=false", url, tmp], capture_output=True, text=True)
    if r.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.exit(f"could not fetch {url}: {r.stderr.strip()}")
    return tmp, tmp, url


def import_bundle(src):
    container = opt("--container", default=DEFAULT_CONTAINER)
    if subprocess.run(["pgrep", "-x", "TrialsFrontier"], capture_output=True).returncode == 0:
        sys.exit("close the game first (pkill -x TrialsFrontier): it keeps its store in memory and would overwrite this")
    data_dir = os.path.join(container, "Documents", "LocalServices")
    store_path = os.path.join(data_dir, "store.json")
    if not os.path.exists(store_path):
        sys.exit(f"no store at {store_path}: start the patched game (local services) once first")
    path, tmp, origin = fetch(src)
    try:
        m = check(path)
        store = json.load(open(store_path))
        store.setdefault("riders", {})
        own = None
        save = os.path.join(container, "Documents", "player.bin")
        if os.path.exists(save):
            raw = decode(open(save, "rb").read())[1]
            own = profile_hashes(raw[276:276 + 40].split(b"\0")[0].decode("ascii", "replace"))[0]
        added = {"riders": 0, "results": 0, "ghosts": 0}
        r = m["rider"]
        if r["game_hash"] == own:
            print(f"{r['name']} is you: your own times are already in the game; importing only the others")
        else:
            rid = take_rider(store, r["game_hash"], r["name"], origin, added)
            if "avatar" in r:
                os.makedirs(os.path.join(data_dir, "avatars"), exist_ok=True)
                shutil.copyfile(os.path.join(path, "avatar.png"), os.path.join(data_dir, "avatars", rid + ".png"))
            for e in m["results"]:
                added["results"] += add_result(store, rid, e, origin)
            for g in m["ghosts"]:
                added["ghosts"] += add_ghost(store, data_dir, rid, g, path, origin)
        for o in m.get("others", []):
            if o["game_hash"] == own:
                continue
            rid = take_rider(store, o["game_hash"], o.get("name"), origin, added)
            for g in o["ghosts"]:
                added["ghosts"] += add_ghost(store, data_dir, rid, g, path, origin)
                added["results"] += add_result(store, rid, {**g, "faults": 0}, origin)
        store.setdefault("bundles", {})[origin] = {"rider": r["name"], "game_hash": r["game_hash"], "created": m["created"]}
        tmp_path = store_path + ".tmp"
        json.dump(store, open(tmp_path, "w"), indent=1)
        os.replace(tmp_path, store_path)
        print(f"imported {origin}: {added['riders']} new riders, {added['results']} better times, "
              f"{added['ghosts']} ghosts (on GLOBAL next time you start the game)")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


def take_rider(store, ghash, name, origin, added):
    """The stored rider with this hash (named opponents are stored under their real profile id, others under
    rider_id(hash)), else a new one."""
    rid = next((r for r in store["riders"] if re.fullmatch(r"[0-9a-f-]{36}", r) and "%08X" % game_hash(r) == ghash),
               rider_id(ghash))
    entry = store["riders"].get(rid)
    if entry is None:
        store["riders"][rid] = {"name": name or "Rider " + ghash, "source": "bundle " + origin}
        added["riders"] += 1
    elif name and entry.get("name", "").startswith("Rider "):  # a downloaded opponent gets its name back
        entry["name"] = name
    return rid


def add_result(store, rid, e, origin):
    ms, faults, bike = e["time_ms"], e.get("faults") or 0, e.get("bike") or 0
    new = {"drivetime": ms, "data": (faults & 0xFF) | ((bike & 0x3F) << 8), "upgrades": 0, "submittime": 0,
           "score_value": 360000000 - ms - faults * 3600000, "extradata": 0, "source": "bundle"}
    board = store["results"].setdefault("track%d" % e["leaderboard"], {})
    old = board.get(rid)
    if old is None or (faults, ms) < (old["data"] & 0xFF, old["drivetime"]):
        board[rid] = new
        return 1
    return 0


def add_ghost(store, data_dir, rid, g, path, origin):
    """One ghost per rider and leaderboard: a faster one replaces the stored one."""
    lb = g["leaderboard"]
    held = [(cid, e) for cid, e in store["ghosts"].items() if e["profile"] == rid and e["track_id"] == lb]
    if held and all(e["metadata"].get("drive_time", 0) <= g["time_ms"] for _, e in held):
        return 0
    for cid, _ in held:
        del store["ghosts"][cid]
        p = os.path.join(data_dir, "ghosts", "%d.bin" % int(cid))
        if os.path.exists(p):
            os.remove(p)  # replaced by the faster ghost; the bundle stays the source
    cid = store["next_id"]
    store["next_id"] += 1
    data = open(os.path.join(path, g["file"]), "rb").read()
    os.makedirs(os.path.join(data_dir, "ghosts"), exist_ok=True)
    open(os.path.join(data_dir, "ghosts", "%d.bin" % cid), "wb").write(data)
    store["ghosts"][str(cid)] = {"profile": rid, "track_id": lb, "source": "bundle " + origin,
                                 "metadata": {"track_id": lb, "drive_time": g["time_ms"], "size": len(data)}}
    return 1


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
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "export" and len(sys.argv) >= 4:
        export(sys.argv[2], sys.argv[3])
    elif cmd == "check" and len(sys.argv) >= 3:
        verify = opt("--verify", True)
        m = check(sys.argv[2], verify)
        print(f"ok: {m['rider']['name']} ({m['rider']['game_hash']}), {len(m['results'])} times, {len(m['ghosts'])} ghosts,"
              f" {len(m.get('others', []))} other riders")
    elif cmd == "publish" and len(sys.argv) >= 3:
        publish(sys.argv[2])
    elif cmd == "import" and len(sys.argv) >= 3:
        import_bundle(sys.argv[2])
    elif cmd == "search":
        search()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
