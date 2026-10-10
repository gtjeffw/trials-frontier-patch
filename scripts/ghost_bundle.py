"""Share Trials Frontier best times and ghosts as "bundles" (to race other riders' bundles: scripts/community.py).

Usage:
  python3 -I ghost_bundle.py export  <game Documents dir> <bundle dir> [--app <TrialsFrontier.app>] [--avatar <png>]
                                     [--name <rider name>] [--license CC0-1.0|CC-BY-4.0]
                                     [--include-others | --include-others-with-names]
  python3 -I ghost_bundle.py update  <bundle dir> [--documents <dir>] [--dry-run]
  python3 -I ghost_bundle.py check   <bundle dir> [--verify]
  python3 -I ghost_bundle.py publish <bundle dir> [--repo <name>] [--sign-key <ssh private key>] [--i-agree]
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
         server served later (possibly from other people's bundles) are never re-shared. Re-exporting into the same
         folder keeps its git history (for publish updates).
update   re-exports a bundle with the options of its first export (kept in the bundle folder's .export.json, never
         published), keeps whatever the bundle already had where it is better (best time and fastest ghost per
         leaderboard), shows the new and better times, and publishes the update (agreement, signature, a new commit
         pushed to the same repository; --dry-run builds the preview instead). Run it whenever you have new best
         times. --documents <dir>: this time from another copy of the same profile, e.g. an iPhone's Documents
         pulled with `scripts/ios_device.py pull-data` (iOS 17+) or copied with Finder (file-sharing build); a
         different profile is refused.
check    validates a bundle the way scripts/community.py does before using it; --verify also checks the manifest signature against the
         publisher's SSH keys on GitHub.
publish  shows what will be published, asks you to agree, then (GitHub CLI `gh`, logged in) creates or updates a
         public repository <you>/trials-frontier-ghosts-<name> with the topics that make bundles findable. Commits
         use your GitHub noreply address. The manifest names you as publisher, states that the rider is you, and is
         always signed with an SSH key on your GitHub account (anyone can check it; a future fan server can use it
         to tie the rider's records to you): a key of yours already on GitHub is found automatically (or
         --sign-key); if there is none, publish offers to create a signing-only key and add it to your account.
         --dry-run publishes nothing and leaves the bundle unchanged: it builds the repository exactly as it would
         be pushed (files, README, signed manifest if you have a key on GitHub, the commit) as a local git
         repository in <bundle dir>-preview, and prints the GitHub commands it would run.
search   lists published bundles (GitHub topic trials-frontier-bundle).
"""
import datetime
import glob
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
from local_services import decode, game_hash, ghost_drive_time, known_riders, read_scores, save_name  # noqa: E402

FORMAT, FORMAT_VERSION = "trials-frontier-bundle", 1
MANIFEST, SIGNATURE = "trials-frontier-bundle.json", "trials-frontier-bundle.json.sig"
SIGN_NAMESPACE = "trials-frontier-bundle"
STATEMENT = ("The publisher states that the rider is their own and that the rider's times and ghosts were recorded "
             "by them; anything under 'others' was downloaded by their game.")
SIGNING_KEY = os.path.expanduser("~/.ssh/trials_frontier_bundle_ed25519")
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


def write_text(out, m):
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
                  f"who states that **{r['name']}** is their own rider and these are their own runs. The manifest is "
                  f"signed with an SSH key of that account (`{SIGNATURE}`); check it with "
                  "`python3 -I scripts/ghost_bundle.py check <this folder> --verify`."]
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
    if verify:
        print(f"signature ok: signed by an SSH key of github.com/{verify_signature(real, m)}")
    return m


_KEYS = {}


def github_keys(login):
    """The public SSH keys of a GitHub account ("<type> <base64>"): authentication and signing keys. Through `gh`
    when it is logged in (higher rate limit), else the public API; cached per run."""
    if login in _KEYS:
        return _KEYS[login]
    use_gh = shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0
    keys = []
    for kind in ("keys", "ssh_signing_keys"):
        try:
            if use_gh:
                r = subprocess.run(["gh", "api", f"users/{login}/{kind}"], capture_output=True, text=True, timeout=30)
                items = json.loads(r.stdout) if r.returncode == 0 else []
            else:
                with urllib.request.urlopen(f"https://api.github.com/users/{login}/{kind}", timeout=20) as r:
                    items = json.load(r)
            keys += [" ".join(k["key"].split()[:2]) for k in items]
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            pass
    _KEYS[login] = keys
    return keys


def verify_with_keys(bundle, login, keys):
    """None if the manifest's signature was made by one of keys, else the reason."""
    sig = os.path.join(bundle, SIGNATURE)
    if not os.path.isfile(sig):
        return "no signature"
    if not keys:
        return f"no SSH keys found for github.com/{login}"
    with tempfile.NamedTemporaryFile("w", suffix=".signers", delete=False) as fh:
        fh.write("".join(f"{login} {k}\n" for k in keys))
    try:
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", fh.name, "-I", login, "-n", SIGN_NAMESPACE, "-s", sig],
                           stdin=open(os.path.join(bundle, MANIFEST), "rb"), capture_output=True, text=True)
    finally:
        os.remove(fh.name)
    return None if r.returncode == 0 else (r.stderr.strip() or r.stdout.strip() or "does not verify")


def verify_signature(bundle, m, keys=None):
    """The GitHub login whose SSH key signed the manifest; BundleError if it is unsigned or does not verify."""
    login = (m.get("publisher") or {}).get("github")
    if not login or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", str(login)):
        raise BundleError("not signed: no publisher")
    err = verify_with_keys(bundle, login, github_keys(login) if keys is None else keys)
    if err:
        raise BundleError(f"signature does NOT match github.com/{login}: {err}")
    return login


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


def find_key(login):
    """A private key in ~/.ssh whose public key is on the GitHub account (signing keys first)."""
    on_github = github_keys(login)
    for pub in sorted(glob.glob(os.path.expanduser("~/.ssh/*.pub")), key=lambda p: p != SIGNING_KEY + ".pub"):
        try:
            mine = " ".join(open(pub).read().split()[:2])
        except OSError:
            continue
        if mine in on_github and os.path.exists(pub[:-4]):
            return pub[:-4]
    return None


def create_key(login):
    """Make a signing-only SSH key for bundles and add it to the GitHub account (with the user's OK)."""
    print(f"\nNone of your SSH keys in ~/.ssh is on github.com/{login}. Bundles are always signed, so publish can create"
          f"\n{SIGNING_KEY} and add it to your GitHub account as a SIGNING key (it cannot be used to log in or"
          "\npush; you can remove it any time under Settings > SSH and GPG keys). GitHub may first ask you to approve"
          "\nthe extra permission in the browser (gh auth refresh -s admin:ssh_signing_key).")
    if input("Create and add the signing key? [y/N] ").strip().lower() not in ("y", "yes"):
        sys.exit("not published (use --sign-key <key> with an SSH key that is on your GitHub account)")
    if not os.path.exists(SIGNING_KEY):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-C", f"trials-frontier-bundle {login}", "-f", SIGNING_KEY],
                       check=True)  # asks for an optional passphrase
    scopes = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
    if "admin:ssh_signing_key" not in scopes.stdout + scopes.stderr:
        subprocess.run(["gh", "auth", "refresh", "-h", "github.com", "-s", "admin:ssh_signing_key"], check=True)
    run(["gh", "ssh-key", "add", SIGNING_KEY + ".pub", "--type", "signing", "--title", "Trials Frontier bundles"])
    return SIGNING_KEY


def names_note(others):
    named = [o["name"] for o in others if o.get("name")]
    if not named:
        return " (by hash only, no names)"
    return f",\n    {len(named)} of them WITH their in-game names ({', '.join(named[:5])}{', …' if len(named) > 5 else ''})"


def publish(bundle):
    repo, key, agreed = opt("--repo"), opt("--sign-key"), opt("--i-agree", True)
    dry, preview = opt("--dry-run", True), opt("--preview-dir")
    m = check(bundle)
    logged_in = shutil.which("gh") and subprocess.run(["gh", "auth", "status"], capture_output=True).returncode == 0
    if logged_in:
        user = json.loads(run(["gh", "api", "user"]))
        login, uid = user["login"], user["id"]
    elif dry:
        login, uid = "YOUR-GITHUB-NAME", 0
    else:
        sys.exit("needs the GitHub CLI, logged in: brew install gh, then gh auth login")
    slug = re.sub(r"[^a-z0-9]+", "-", m["rider"]["name"].lower()).strip("-") or m["rider"]["game_hash"].lower()
    repo = repo or f"trials-frontier-ghosts-{slug}"
    full = f"{login}/{repo}"
    others = m.get("others", [])
    print(f"\n{'PREVIEW of publishing' if dry else 'Publish'} {bundle} as https://github.com/{full} (public)\n")
    print(CONSENT.format(license=m["license"], name=m["rider"]["name"],
                         avatar=" and avatar" if "avatar" in m["rider"] else "",
                         others=OTHERS.format(n=len(others), names=names_note(others)) if others else ""))
    if dry:
        # everything happens in a copy: the repository exactly as it would be pushed, as a local git repository
        target = os.path.abspath(preview or bundle.rstrip("/") + "-preview")
        marker = os.path.join(target, ".git", "trials-frontier-preview")
        if os.path.exists(target):
            if not os.path.exists(marker):
                sys.exit(f"{target} exists and is not an earlier preview; choose --preview-dir")
            shutil.rmtree(target)
        shutil.copytree(bundle, target, symlinks=True)
    else:
        target = bundle
        if not agreed and input('\nType "I agree" to publish: ').strip().lower() != "i agree":
            sys.exit("not published")

    key = key or (find_key(login) if logged_in else None) or (None if dry else create_key(login))
    m["publisher"] = {"github": login, "statement": STATEMENT}
    json.dump(m, open(os.path.join(target, MANIFEST), "w"), indent=1, ensure_ascii=False)
    write_text(target, m)
    sig = os.path.join(target, SIGNATURE)
    if os.path.exists(sig):
        os.remove(sig)
    if key:
        run(["ssh-keygen", "-Y", "sign", "-f", key, "-n", SIGN_NAMESPACE, os.path.join(target, MANIFEST)])
        err = verify_with_keys(target, login, github_keys(login))
        if err and not dry:  # never publish a signature nobody can check
            os.remove(sig)
            sys.exit(f"the signature does not verify against github.com/{login}'s keys ({err}); not published.\n"
                     f"Is {key}.pub on your GitHub account (Settings > SSH and GPG keys)?")
        signed = f"signed with {key}" + (f" (does NOT verify against github.com/{login}: {err})" if err else
                                         f", verifies against github.com/{login}")
    else:
        signed = "NOT signed in this preview: a real publish offers to create a signing key and add it to GitHub"

    noreply = f"{uid}+{login}@users.noreply.github.com"
    if not os.path.isdir(os.path.join(target, ".git")):
        run(["git", "init", "-q", "-b", "main"], cwd=target)
    exclude = os.path.join(target, ".git", "info", "exclude")
    os.makedirs(os.path.dirname(exclude), exist_ok=True)
    if EXPORT_OPTIONS not in (open(exclude).read().split() if os.path.exists(exclude) else []):
        open(exclude, "a").write(f"\n{EXPORT_OPTIONS}\n")  # local paths: never published
    if dry:
        open(marker, "w").write("made by ghost_bundle.py publish --dry-run\n")
    run(["git", "config", "user.name", login], cwd=target)
    run(["git", "config", "user.email", noreply], cwd=target)  # never your private email
    run(["git", "add", "-A"], cwd=target)
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=target).returncode != 0:
        run(["git", "commit", "-q", "-m", f"Trials Frontier ghosts of {m['rider']['name']} ({m['created']})"], cwd=target)
    desc = (f"Trials Frontier (iOS) best times and ghosts of {m['rider']['name']} "
            f"- {FORMAT} v{FORMAT_VERSION}, rider {m['rider']['game_hash']}")
    exists = logged_in and subprocess.run(["gh", "repo", "view", full], capture_output=True).returncode == 0
    if exists:
        if "origin" not in run(["git", "remote"], cwd=target).split():
            run(["git", "remote", "add", "origin", f"https://github.com/{full}.git"], cwd=target, dry=dry)
        # with gh's login for this one push (no change to your git configuration)
        run(["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential", "push", "-u",
             "origin", "main"], cwd=target, dry=dry)
        run(["gh", "repo", "edit", full, "--description", desc], dry=dry)
    else:
        run(["gh", "repo", "create", full, "--public", "--description", desc, "--source", target, "--remote",
             "origin", "--push"], dry=dry)
    run(["gh", "repo", "edit", full] + [a for t in TOPICS for a in ("--add-topic", t)], dry=dry)
    if dry:
        files = subprocess.run(["git", "ls-files"], cwd=target, capture_output=True, text=True).stdout.split()
        size = sum(os.path.getsize(os.path.join(target, f)) for f in files)
        print(f"\nPreview (nothing was published; {bundle} is unchanged): {target}\n"
              f"  {len(files)} files, {size // 1024} KB, {signed}\n"
              f"  description: {desc}\n  topics: {', '.join(TOPICS)}\n"
              f"  look at README.md and {MANIFEST} there, or: git -C {target} show --stat")
    else:
        print(f"published: https://github.com/{full} ({signed})")


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
    elif cmd == "check" and len(sys.argv) >= 3:
        verify = opt("--verify", True)
        m = check(sys.argv[2], verify)
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
