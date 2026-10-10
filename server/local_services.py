"""Local game-services server for the `local-services` patch group (prototype, Python stdlib only).

Usage: python3 -I server/local_services.py [--container <app container Data dir>] [--port 7979]
                                           [--profile-id <uuid>] [--name <name>] [--avatars <dir>] [--log <file>]
                                           [--data <dir>] [--community <layer dir>]

Listens on 127.0.0.1 only. The patched game sends every request here (see docs/JOURNAL.md, "Online services probe"):
  GET  /v1/applications/<appId>/configuration   app configuration; its sandbox "triag_ip_lnch61_a_ws" names the game server
  GET  /profile/?epoch=1                        network time for the mobile login library ("Server-Time:" header)
  POST /v2/profiles/sessions                    mobile login library: create device account / get session ticket
  PUT  /v1/profiles/sessions                    ticket renewal
  .../public/...                                game server (leaderboards, ghosts)
  GET  /avatars/<profileId>/default_146_146.png profile picture: <avatars dir>/<profileId>.png (146x146 PNG);
  GET  /avatars/fallback_146_146.png            default picture: <avatars dir>/fallback.png
Every request is logged; anything not handled yet is answered 404 and marked UNHANDLED so it can be implemented.
The player's profile id and name are read from the container's Documents/player.bin unless given.

Results and ghosts live in a store (--data, default <container>/Documents/LocalServices, as for the in-app server
inapp/: store.json + ghosts/<id>.bin + avatars/; a store in Library/LocalServices is moved there once),
seeded on start from the save's score table and the player's own ghost_<hash>_<leaderboard>.bin files. As with the
original service, a submitted result (resultservice/v1/enhancestats/...) is "updated" only if it beats the stored
one (fewer faults, then less time); the game uploads a ghost only after such a reply, and the store keeps one ghost
per player and leaderboard, refusing a slower one. The Hall of Fame (POST playerstats/v1/stats/global_stats after
every race, the overall score the game computes from its best times; shown as global_score x 100000) is one entry
per player in the "global_stats" board, replaced by each newer score and ranked highest first.

Other riders: opponent ghosts the game downloaded (Documents/robot_ghost-*.robot, avatars robot_image-*.robot) are
imported once. More come from a community layer (scripts/community.py: ghost bundles, the 2019 world records):
<data>/community (installed by community.py) or --community. It is overlaid when the store loads and never written
into store.json: riders merge by the game's hash of their profile id, a layer result shows only where it beats the
stored one, layer ghosts keep their own content ids (from 1000000000) and files, and the player's own rider in
the layer is skipped (only its avatar is used). They appear on GLOBAL; FRIENDS asks only for the player's own id.
"""
import base64
import hashlib
import json
import os
import re
import struct
import sys
import threading
import time
import uuid
import zlib
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from decode_save import decode  # noqa: E402

DEFAULT_CONTAINER = os.path.expanduser("~/Library/Containers/com.ubisoft.redlynx.trialsfrontier/Data")
GAME_SERVER_SANDBOX = "triag_ip_lnch61_a_ws"


def opt(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return default


def game_hash(s):
    """mt::String::getHashCode (ghost file names use it on the profile id)."""
    b = s.encode()
    n, x = len(b), 0
    for c in b:
        c = c - 256 if c > 127 else c
        x = (x + n * c) & 0xFFFFFFFF
        n = ((n & 0xFFFF) * 18000 + (n >> 16)) & 0xFFFFFFFF
    return x


COMMUNITY_FORMAT, COMMUNITY_VERSION, COMMUNITY_BASE = "trials-frontier-community", 1, 1_000_000_000
GLOBAL_BOARD = "global_stats"  # the Hall of Fame (overall score), not a track
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def placeholder(name):
    """The names the server makes up for riders it knows only by hash."""
    return not name or re.fullmatch(r"(?i)rider( [0-9A-F]{8})?", name) is not None


def read_scores(raw):
    """{leaderboard id: (faults, time ms, bike)} from the save's score table (see scripts/extract_scores.py)."""
    def is_record(off):
        f = struct.unpack_from("<16I", raw, off)
        # PlayerScores byte 0 is a state byte the game changes after a race (0xff for most records, 0 after
        # replaying one), so only the integrity copy and a plausible leaderboard id identify a record. Id 0 is the
        # overall "global_stats" leaderboard, added once the player is logged in.
        return f[0] < 0x1000000 and (f[9] == 0 or f[9] + f[10] + f[8] * 3600000 == 360000000)
    best = None
    for start in range(0, len(raw) - 68, 4):
        n = struct.unpack_from("<I", raw, start)[0]
        if 1 <= n <= 2000 and start + 4 + n * 64 <= len(raw) and all(is_record(start + 4 + i * 64) for i in range(n)):
            timed = sum(1 for i in range(n) if struct.unpack_from("<I", raw, start + 4 + i * 64 + 36)[0])
            if best is None or timed > best[2]:  # the real table has the most timed records
                best = (start, n, timed)
    scores = {}
    if best:
        for i in range(best[1]):
            f = struct.unpack_from("<16I", raw, best[0] + 4 + i * 64)
            if f[9]:
                scores[f[0]] = (f[8], f[9], f[11])
    return scores


def ghost_drive_time(data):
    """Drive time (ms) recorded in a ghost: 16-byte header (u32 version, checksum, size, 0) + zlib body;
    version 3 bodies start with u32 bike id, u32 drive time; version 2 with the drive time. None if unreadable."""
    try:
        version = struct.unpack_from("<I", data, 0)[0]
        body = zlib.decompress(data[16:])
        return struct.unpack_from("<I", body, 4 if version >= 3 else 0)[0]
    except (struct.error, zlib.error):
        return None


def unscramble(data, seed=0x97, mult=0x1F49):
    """mt::file::SaveFile default Protection (also used by level files and robot images)."""
    out = bytearray(data)
    key = seed
    for i in range(len(out)):
        out[i] ^= key & 0xFF
        key = (key * mult) & 0xFFFFFFFF
    return bytes(out)


def robot_avatar_png(data):
    """robot_image-<hash>.robot: SaveFile (default Protection, 16-byte header) holding 'OBOR' + 12 bytes + PNG."""
    body = unscramble(data)[16:]
    i = body.find(b"\x89PNG")
    return body[i:] if body[:4] == b"OBOR" and i >= 0 else None


def known_riders(raw):
    """(name, profile id) pairs the save keeps for opponents: a name followed 129 bytes later by its profile id."""
    out = {}
    for m in re.finditer(rb"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw):
        name = raw[m.start() - 129:m.start() - 1].split(b"\0")[0]
        if 3 <= len(name) <= 32 and re.fullmatch(rb"[ -~]+", name):
            out[m.group().decode()] = name.decode()
    return out


def requested_name(headers):
    """The name in a mobile-login-library request: "Authorization: UbiMobile_v1 t=<base64 of
    account:secret:base64(name)>". The "change account name" request (ubimobile changeAccountName, sent after every
    login once the player has picked a name in the tutorial or the options) carries the new name; a normal login
    carries the name the library last got from us, which before the player has a name is our placeholder. So
    placeholders ("Rider") are never returned, and real names are adopted."""
    m = re.fullmatch(r"UbiMobile_v1 t=([A-Za-z0-9+/=]+)", (headers.get("Authorization") or "").strip())
    if not m:
        return None
    try:
        parts = base64.b64decode(m.group(1)).decode("utf-8").split(":")
        name = base64.b64decode(parts[2]).decode("utf-8") if len(parts) == 3 else None
    except (ValueError, UnicodeDecodeError):
        return None
    return name if name and len(name) <= 32 and name.isprintable() and not placeholder(name) else None


def save_name(raw):
    """The player's name: the platform (Ubisoft) name at raw offset 20 (Player+0x10), else the nickname typed in
    the tutorial (MenuzMissionTaskEnterName), a 24-byte field 148 bytes before the end of the save (version 114)."""
    name = raw[20:20 + 128].split(b"\0")[0]
    if not name and len(raw) >= 148:
        name = raw[len(raw) - 148:len(raw) - 124].split(b"\0")[0]
    return name.decode("utf-8", "replace")


def read_profile(container):
    """(profile id, name) from player.bin: name at raw offset 20 (Player+0x10), profile id at 276 (Player+0x110).
    ("", "") before the game has written its first save."""
    path = os.path.join(container, "Documents", "player.bin")
    if not os.path.exists(path):
        return "", ""
    _, raw = decode(open(path, "rb").read())
    name = save_name(raw)
    pid = raw[276:276 + 40].split(b"\0")[0].decode("ascii", "replace")
    return pid, name


class Services:
    def __init__(self, container, port, profile_id, name, log_path, avatars=None):
        self.container, self.port, self.avatars = container, port, avatars
        self.base = f"http://127.0.0.1:{port}"
        self.fixed_name, self.save_mtime = name, None
        self.profile_id, self.name = profile_id or read_profile(container)[0], "Rider"
        self.refresh_name()
        self.log = open(log_path, "a", buffering=1) if log_path else None

    def refresh_name(self):
        """The player's name: --name, else the last name the game asked for (change-name request; the save only
        catches up later), else the save's (re-read when player.bin changes), else "Rider"."""
        if self.fixed_name:
            self.name = self.fixed_name
            return
        if getattr(self, "store", None) and self.store.get("player_name"):
            self.name = self.store["player_name"]
            return
        try:
            mtime = os.stat(self.documents("player.bin")).st_mtime_ns
        except OSError:
            return
        if mtime != self.save_mtime:
            self.save_mtime = mtime
            self.name = read_profile(self.container)[1] or self.name

    def note(self, line):
        line = time.strftime("%H:%M:%S ") + line
        print(line, flush=True)
        if self.log:
            self.log.write(line + "\n")

    @property
    def ticket(self):
        return "local-" + uuid.uuid5(uuid.NAMESPACE_URL, self.profile_id).hex

    def session(self):
        self.refresh_name()
        now = time.gmtime()
        return {
            "platformType": "uplay",
            "ticket": self.ticket,
            "profileId": self.profile_id,
            "userId": self.profile_id,
            "nameOnPlatform": self.name,
            "environment": "Prod",
            "expiration": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(time.time() + 3 * 3600)),
            "serverTime": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", now),
            "sessionId": str(uuid.uuid5(uuid.NAMESPACE_OID, self.ticket)),
        }

    def documents(self, name=""):
        return os.path.join(self.container, "Documents", name)

    def save_raw(self):
        path = self.documents("player.bin")
        return decode(open(path, "rb").read())[1] if os.path.exists(path) else b""

    def scores(self):
        raw = self.save_raw()
        return read_scores(raw) if raw else {}

    # ---- persistent store (results and ghosts), seeded from the save and its ghost files ----

    def load_store(self, data_dir, community=None):
        self.data_dir = data_dir
        self.shadow_results, self.shadow_riders, self.community_ghosts, self.community_avatars = {}, {}, set(), {}
        self.community_dir = None
        os.makedirs(os.path.join(data_dir, "ghosts"), exist_ok=True)
        self.lock = threading.RLock()
        path = os.path.join(data_dir, "store.json")
        self.store = json.load(open(path)) if os.path.exists(path) else {"results": {}, "ghosts": {}, "next_id": 1000}
        if not self.profile_id:  # a new player: no save yet; the game keeps the id the login returns
            self.profile_id = self.store.setdefault("new_player_profile", str(uuid.uuid4()))
        seeded = 0
        for lb, (faults, ms, bike) in self.scores().items():
            board = self.store["results"].setdefault("track%d" % lb, {})
            if self.profile_id not in board:
                board[self.profile_id] = {"drivetime": ms, "data": (faults & 0xFF) | ((bike & 0x3F) << 8), "upgrades": 0,
                                          "submittime": 0, "score_value": 360000000 - ms - faults * 3600000,
                                          "extradata": 0, "source": "save"}
                seeded += 1
        prefix = "ghost_%08x_" % game_hash(self.profile_id)
        held = {g["track_id"] for g in self.store["ghosts"].values() if g["profile"] == self.profile_id}
        scores = self.scores()
        for f in sorted(os.listdir(self.documents())):
            m = re.fullmatch(re.escape(prefix) + r"(\d+)\.bin", f)
            if m and int(m.group(1)) not in held:  # the store's own (possibly newer) ghost wins
                lb = int(m.group(1))
                data = open(self.documents(f), "rb").read()
                cid = self.new_id()
                open(self.ghost_path(cid), "wb").write(data)
                self.store["ghosts"][str(cid)] = {"profile": self.profile_id, "track_id": lb, "source": f,
                                                  "metadata": {"track_id": lb, "size": len(data), "drive_time":
                                                               ghost_drive_time(data) or scores.get(lb, (0, 0, 0))[1]}}
                seeded += 1
        self.store.setdefault("riders", {})
        seeded += self.import_robots()
        self.drop_legacy_world_records()
        self.load_community(community)
        self.save_store()
        self.note(f"store {data_dir}: {sum(len(b) for b in self.store['results'].values())} results, "
                  f"{len(self.store['ghosts'])} ghosts, {len(self.store['riders'])} other riders "
                  f"({seeded} imported now, {len(self.community_ghosts)} ghosts from the community layer)")

    def drop_legacy_world_records(self):
        """World records used to be imported into the store; they now come from the community layer."""
        if not self.store.pop("world_records_imported", None):
            return
        gone = {rid for rid, r in self.store["riders"].items() if r.get("source") == "wr2019"}
        for rid in gone:
            del self.store["riders"][rid]
        for name in list(self.store["results"]):
            board = self.store["results"][name]
            for rid in [r for r, st in board.items() if st.get("source") == "wr2019"]:
                del board[rid]
            if not board:
                del self.store["results"][name]
        self.note(f"removed {len(gone)} world-record riders imported by an older version (now: community layer)")

    def load_community(self, folder):
        """Overlay the community layer (see the module notes); shadow_* remember what it replaced, for save_store."""
        folder = folder or os.path.join(self.data_dir, "community")
        path = os.path.join(folder, "community.json")
        if not os.path.exists(path):
            return
        try:
            layer = json.load(open(path))
        except ValueError as e:
            self.note(f"community layer {folder} unreadable ({e}); ignored")
            return
        if layer.get("format") != COMMUNITY_FORMAT or layer.get("format_version") != COMMUNITY_VERSION:
            self.note(f"community layer {folder}: format {layer.get('format_version')} not supported; ignored")
            return
        self.community_dir = folder
        own = "%08X" % game_hash(self.profile_id)
        own_sha = hashlib.sha256(("trials-frontier-profile:" + self.profile_id).encode()).hexdigest()
        by_hash = {"%08X" % game_hash(r): r for r in sorted(self.store["riders"]) if UUID.fullmatch(r)}
        hash_count = {}
        for c in layer["riders"].values():
            if c.get("game_hash"):
                hash_count[c["game_hash"]] = hash_count.get(c["game_hash"], 0) + 1
        rid_map = {}
        for crid in sorted(layer["riders"]):
            c = layer["riders"][crid]
            h = c.get("game_hash")
            avatar = os.path.join(folder, "avatars", crid + ".png")
            # the player: by the sha256 of the profile id; a rider known only by the 32-bit hash, by the hash
            if c.get("profile_sha256") == own_sha or (h and h == own and not c.get("profile_sha256")):
                if os.path.isfile(avatar) and c.get("profile_sha256") == own_sha:
                    self.community_avatars[self.profile_id] = avatar
                continue
            # a downloaded opponent already in the store: linked by the hash only if no other layer rider has it
            robot = str(uuid.uuid5(uuid.NAMESPACE_URL, "trials-frontier-robot:" + h)) if h else None
            if crid in self.store["riders"] or not h or hash_count.get(h) != 1:
                rid = crid
            else:
                rid = robot if robot in self.store["riders"] else by_hash.get(h, crid)
            rid_map[crid] = rid
            if os.path.isfile(avatar):
                self.community_avatars[rid] = avatar
            cur = self.store["riders"].get(rid)
            if cur is None or (placeholder(cur.get("name")) and not placeholder(c.get("name"))):
                self.shadow_riders.setdefault(rid, cur)
                self.store["riders"][rid] = {"name": c.get("name") or "Rider " + (h or "?"), "source": "community"}
        for name in sorted(layer["results"]):
            for crid, st in sorted(layer["results"][name].items()):
                rid = rid_map.get(crid)
                if rid is None:
                    continue
                board = self.store["results"].setdefault(name, {})
                if self.better(st, board.get(rid)):
                    self.shadow_results.setdefault((name, rid), board.get(rid))
                    board[rid] = st
        for cid in sorted(layer["ghosts"], key=int):
            g = layer["ghosts"][cid]
            rid = rid_map.get(g["profile"])
            if rid is None or int(cid) < COMMUNITY_BASE or cid in self.store["ghosts"]:
                continue
            self.store["ghosts"][cid] = dict(g, profile=rid)
            self.community_ghosts.add(cid)
        self.note(f"community layer {folder}: {len(rid_map)} riders, {len(self.shadow_results)} results shown, "
                  f"{len(self.community_ghosts)} ghosts")

    def persisted(self):
        """The store without the community layer."""
        if not (self.shadow_results or self.shadow_riders or self.community_ghosts):
            return self.store
        out = dict(self.store)
        out["results"] = dict(self.store["results"])
        for (name, rid), old in self.shadow_results.items():
            if out["results"][name] is self.store["results"][name]:
                out["results"][name] = dict(self.store["results"][name])
            if old is None:
                out["results"][name].pop(rid, None)
            else:
                out["results"][name][rid] = old
        for name in {name for name, _ in self.shadow_results}:
            if not out["results"][name]:  # a board only the layer had
                del out["results"][name]
        out["riders"] = dict(self.store["riders"])
        for rid, old in self.shadow_riders.items():
            if old is None:
                out["riders"].pop(rid, None)
            else:
                out["riders"][rid] = old
        out["ghosts"] = {k: v for k, v in self.store["ghosts"].items() if k not in self.community_ghosts}
        return out

    def add_rider(self, rider_id, name, source):
        self.store["riders"].setdefault(rider_id, {"name": name, "source": source})

    def add_result(self, board_name, rider_id, faults, ms, bike, source):
        """Add another rider's result unless one is stored; keep the better one if both platforms have it."""
        board = self.store["results"].setdefault(board_name, {})
        new = {"drivetime": ms, "data": (faults & 0xFF) | ((bike & 0x3F) << 8), "upgrades": 0, "submittime": 0,
               "score_value": 360000000 - ms - faults * 3600000, "extradata": 0, "source": source}
        if self.better(new, board.get(rider_id)):
            board[rider_id] = new
            return 1
        return 0

    def import_robots(self):
        """Opponent ghosts the game downloaded ("beat this rider"): Documents/robot_ghost-<HASH>-<LBHEX>.robot,
        avatars in robot_image-<HASH>.robot. HASH = getHashCode(profile id), so riders stay anonymous unless the save
        names them (known_riders); everyone else becomes "Rider <HASH>" under a stable made-up id."""
        if self.store.get("robots_imported"):
            return 0
        raw = self.save_raw()
        named = {"%08X" % game_hash(pid): (pid, name) for pid, name in known_riders(raw).items()}
        count = 0
        os.makedirs(os.path.join(self.data_dir, "avatars"), exist_ok=True)
        for f in sorted(os.listdir(self.documents())):
            m = re.fullmatch(r"robot_ghost-([0-9A-F]+)-([0-9A-F]+)\.robot", f)
            if not m:
                continue
            h, lb = m.group(1).zfill(8), int(m.group(2), 16)
            data = open(self.documents(f), "rb").read()
            ms = ghost_drive_time(data)
            if not ms:
                continue
            rid, name = named.get(h, (str(uuid.uuid5(uuid.NAMESPACE_URL, "trials-frontier-robot:" + h)), "Rider " + h))
            self.add_rider(rid, name, "robot")
            bike = struct.unpack_from("<I", zlib.decompress(data[16:]), 0)[0]
            count += self.add_result("track%d" % lb, rid, 0, ms, bike, "robot")
            cid = self.new_id()
            open(self.ghost_path(cid), "wb").write(data)
            self.store["ghosts"][str(cid)] = {"profile": rid, "track_id": lb, "source": f,
                                              "metadata": {"track_id": lb, "drive_time": ms, "size": len(data)}}
            img = self.documents("robot_image-%s.robot" % m.group(1))
            png = robot_avatar_png(open(img, "rb").read()) if os.path.exists(img) else None
            if png:
                open(os.path.join(self.data_dir, "avatars", rid + ".png"), "wb").write(png)
        self.store["robots_imported"] = True
        return count

    def new_id(self):
        with self.lock:
            cid = self.store["next_id"]
            self.store["next_id"] += 1
            return cid

    def ghost_path(self, cid):
        if str(int(cid)) in self.community_ghosts:
            return os.path.join(self.community_dir, "ghosts", "%d.bin" % int(cid))
        return os.path.join(self.data_dir, "ghosts", "%d.bin" % int(cid))

    def save_store(self):
        with self.lock:
            tmp = os.path.join(self.data_dir, "store.json.tmp")
            json.dump(self.persisted(), open(tmp, "w"), indent=1)
            os.replace(tmp, os.path.join(self.data_dir, "store.json"))

    @staticmethod
    def better(new, old):
        """Fewer faults first, then less time (the game's own ordering: faults outrank time)."""
        return old is None or ((new["data"] & 0xFF), new["drivetime"]) < ((old["data"] & 0xFF), old["drivetime"])

    def board(self, name):
        results = self.store["results"]
        if name in results:
            return results[name]
        m = re.fullmatch(r"track(\d+)", name)
        if m:
            base = int(m.group(1))
            for key in sorted(results):
                k = re.fullmatch(r"track(\d+)", key)
                if k and int(k.group(1)) & 0xFFFF == base:
                    return results[key]
        return {}

    def leaderboard(self, name, query):
        if name == GLOBAL_BOARD:  # Hall of Fame: highest overall score first
            order = lambda kv: (-float(kv[1].get("global_score", 0)), kv[0])
        else:
            order = lambda kv: ((kv[1]["data"] & 0xFF), kv[1]["drivetime"], kv[0])
        entries = sorted(self.board(name).items(), key=order)
        rows = [{"player": pid, "rank": i + 1, "stats": {k: v for k, v in st.items() if k != "source"}}
                for i, (pid, st) in enumerate(entries)]
        total = len(rows)
        if "players" in query:
            wanted = set(",".join(query["players"]).split(","))
            rows = [r for r in rows if r["player"] in wanted]
        elif "range" in query:
            a, b = (int(x) for x in query["range"][0].split(",")[:2])
            rows = rows[max(a, 1) - 1:b]
        elif "around" in query:
            pid, _, n = query["around"][0].partition(",")
            n = int(n or 10)
            i = next((i for i, r in enumerate(rows) if r["player"] == pid), 0)
            rows = rows[max(0, i - n // 2):max(0, i - n // 2) + n]
        return {"leaderboard": name, "playerCount": total, "results": rows}

    def submit(self, name, update):
        st = update.get("stats", update)
        new = {k: st.get(k, 0) for k in ("drivetime", "data", "upgrades", "submittime", "score_value", "extradata")}
        if not new["drivetime"]:
            return False
        with self.lock:
            board = self.store["results"].setdefault(name, {})
            old = board.get(self.profile_id)
            improved = self.better(new, old)
            if improved:
                board[self.profile_id] = new
                self.save_store()
        self.note(f"   result {name}: {new['data'] & 0xFF}F {new['drivetime']} ms -> "
                  + ("NEW BEST" if improved else f"not better than {old['data'] & 0xFF}F {old['drivetime']} ms"))
        return improved

    def submit_global(self, update):
        """Hall of Fame: the overall score the game computes from all its best times and sends after every race
        (POST playerstats/v1/stats/global_stats; shown as global_score x 100000). One entry per player in the
        "global_stats" board, replaced by each newer value: an aggregate, not a copy of the track results."""
        st = update.get("stats", update)
        try:
            score = float(st.get("global_score"))
        except (TypeError, ValueError):
            return False
        new = {"global_score": score, **{k: st.get(k, 0) for k in ("data", "drivetime", "upgrades", "submittime")}}
        with self.lock:
            board = self.store["results"].setdefault(GLOBAL_BOARD, {})
            old = board.get(self.profile_id)
            changed = old is None or old.get("global_score") != score
            if changed:
                board[self.profile_id] = new
                self.save_store()
        self.note(f"   hall of fame: {int(score * 100000):,}" + ("" if changed else " (unchanged)"))
        return changed

    def parse_updates(self, body):
        try:
            req = json.loads(body)
        except ValueError:
            req = json.loads(re.sub(rb",\s*([}\]])", rb"\1", body))
        ups = req.get("updates", [])
        return ups if isinstance(ups, list) else [ups]

    # ---- ghosts (user storage) ----

    def ghosts_for(self, profile, track):
        out = [(int(cid), g) for cid, g in self.store["ghosts"].items() if g["profile"] == profile and g.get("payload", True)
               and (g["track_id"] == track or g["track_id"] & 0xFFFF == track)]
        return sorted(out, key=lambda x: (x[1]["track_id"] != track, x[1]["metadata"].get("drive_time") or 1 << 31, x[0]))

    def replay_id(self, body):
        req = json.loads(body or b"{}")
        m = re.search(r"(\d+)$", str(req.get("track_name", "")))
        hits = self.ghosts_for(req.get("profile_id"), int(m.group(1))) if m else []
        exact = [h for h in hits if h[1]["metadata"].get("drive_time") == req.get("drive_time")]
        cid = (exact or hits or [(0, None)])[0][0]
        self.note(f"   replay {cid} for {req.get('track_name')} {req.get('drive_time')} ms" if cid else
                  f"   no ghost for {req.get('track_name')}")
        return {"replay_id": cid}

    def search_ghost(self, query):
        track = int(query.get("track_id", ["-1"])[0])
        players = ",".join(query.get("players", [])).split(",")
        contents = []
        for pid in players:
            hits = self.ghosts_for(pid, track)
            if "drive_time" in query:
                hits = [h for h in hits if h[1]["metadata"].get("drive_time") == int(query["drive_time"][0])] or hits
            for cid, g in hits[:1]:
                contents.append({"contentId": cid, "profileId": pid, "metadata": g["metadata"]})
        return {"contents": contents}

    def parse_metadata(self, body):
        text = body.decode("utf-8", "replace").strip()
        text += "}" * max(0, text.count("{") - text.count("}"))
        try:
            return json.loads(text).get("metadata", {})
        except ValueError:
            return {k: int(v) for k, v in re.findall(r'"(\w+)"\s*:\s*(-?\d+)', text)}

    def best_time(self, track):
        st = self.store["results"].get("track%d" % track, {}).get(self.profile_id)
        return st["drivetime"] if st else None

    def acceptable(self, track, drive_time):
        """A ghost is stored only if it is the run behind the player's current best result for that leaderboard
        (the game uploads only after the result service answered "updated"; its resync path re-sends the same run).
        Without a stored result, accept it unless a faster ghost is already held."""
        best = self.best_time(track)
        if best is not None:
            return drive_time == best
        held = [g for _, g in self.ghosts_for(self.profile_id, track) if g["track_id"] == track]
        return not held or drive_time <= (held[0]["metadata"].get("drive_time") or 1 << 31)

    def ghost_content_for(self, track):
        """GET resultservice/v1/replaydata?track_id=N: the player's existing ghost content for an exact leaderboard."""
        hits = [cid for cid, g in self.ghosts_for(self.profile_id, track) if g["track_id"] == track]
        return {"content_id": hits[0] if hits else 0}

    def add_ghost(self, body):
        meta = self.parse_metadata(body)
        track = meta.get("track_id", -1)
        if meta.get("drive_time") and not self.acceptable(track, meta["drive_time"]):
            self.note(f"   refused ghost track {track}: {meta['drive_time']} ms is not the current best "
                      f"({self.best_time(track)} ms)")
            return 409, {"errorCode": 409, "message": "not the current best run"}
        cid = self.new_id()
        with self.lock:
            self.store["ghosts"][str(cid)] = {"profile": self.profile_id, "track_id": track, "metadata": meta,
                                              "payload": False}
            self.save_store()
        self.note(f"   new ghost content {cid} for track {track} ({meta.get('drive_time')} ms)")
        return 200, {"contentId": cid, "payloadUploadUrl": f"{self.base}/public/userstorage/v2/content/ghost/{cid}/payload"}

    def put_ghost_payload(self, cid, body):
        g = self.store["ghosts"].get(str(cid))
        if not g or g["profile"] != self.profile_id:
            return 404, {"errorCode": 404, "message": "unknown content"}
        ms = ghost_drive_time(body)
        if ms is not None and not self.acceptable(g["track_id"], ms):
            self.note(f"   refused ghost payload for track {g['track_id']}: {ms} ms is not the current best "
                      f"({self.best_time(g['track_id'])} ms)")
            return 409, {"errorCode": 409, "message": "not the current best run"}
        with self.lock:
            open(self.ghost_path(cid), "wb").write(body)
            g["payload"] = True
            g["metadata"]["size"] = len(body)
            if ms is not None:
                g["metadata"]["drive_time"] = ms
            g.pop("source", None)
            # keep one ghost per profile and leaderboard: drop older contents for the same track
            for other, o in list(self.store["ghosts"].items()):
                if other != str(cid) and o["profile"] == g["profile"] and o["track_id"] == g["track_id"]:
                    del self.store["ghosts"][other]
            self.save_store()
        self.note(f"   stored ghost {cid}: track {g['track_id']}, {len(body)} bytes")
        return 200, {"contentId": int(cid)}

    def put_ghost_metadata(self, cid, body):
        g = self.store["ghosts"].get(str(cid))
        if not g:
            return 404, {"errorCode": 404, "message": "unknown content"}
        with self.lock:
            g["metadata"].update({k: v for k, v in self.parse_metadata(body).items() if k != "size"})
            self.save_store()
        return 200, {"contentId": int(cid)}

    def rider_name(self, pid):
        if pid == self.profile_id:
            self.refresh_name()
            return self.name
        return self.store["riders"].get(pid, {}).get("name", "rider")

    def profiles(self, query):
        ids = ",".join(query.get("profileId", [])).split(",")
        return {"profiles": [{"profileId": i, "userId": i, "idOnPlatform": i, "platformType": "uplay",
                              "nameOnPlatform": self.rider_name(i)} for i in ids if i]}

    # ---- robots: "live opponents" for A.N.B.A. (RobotmanManager / OnlineRobotMission) and mission ghosts ----

    def robot_candidates(self, track):
        """Other riders' ghosts on a leaderboard (exact id, else same base track); the player's own only if there
        is no one else. Each: (rider id, content id, ghost entry, drive time)."""
        others, own = [], []
        for cid, g in sorted(self.store["ghosts"].items(), key=lambda kv: int(kv[0])):
            if not g.get("payload", True) or not (g["track_id"] == track or g["track_id"] & 0xFFFF == track):
                continue
            entry = (g["profile"], int(cid), g, g["metadata"].get("drive_time") or 0)
            (own if g["profile"] == self.profile_id else others).append(entry)
        exact = [e for e in others if e[2]["track_id"] == track]
        return exact or others or [e for e in own if e[2]["track_id"] == track] or own

    def pick_robot(self, track, target_ms=None, offset=0):
        """Closest opponent just slower than the player's best (beatable but close); faster ones if none is
        slower; the slowest when the player has no time. `offset` steps to the next candidate."""
        cands = [c for c in self.robot_candidates(track) if c[3]]
        if not cands:
            return None
        if target_ms is None:
            best = self.store["results"].get("track%d" % track, {}).get(self.profile_id)
            target_ms = best["drivetime"] if best else None
        if target_ms is None:
            order = sorted(cands, key=lambda c: (-c[3], c[1]))
        else:
            slower = sorted((c for c in cands if c[3] >= target_ms), key=lambda c: (c[3], c[1]))
            faster = sorted((c for c in cands if c[3] < target_ms), key=lambda c: (-c[3], c[1]))
            order = slower + faster
        return order[offset % len(order)]

    def robot_reply(self, pick, track):
        rider, cid, g, ms = pick
        st = self.store["results"].get("track%d" % g["track_id"], {}).get(rider) or {}
        data = st.get("data", 0)
        return {"player": rider, "drivetime": ms, "upgrades": st.get("upgrades", 0), "data": data,
                "score_value": st.get("score_value", 360000000 - ms - (data & 0xFF) * 3600000), "replay_id": cid}

    def robot(self, query):
        m = re.search(r"(\d+)$", query.get("track_name", [""])[0])
        if not m:
            return None
        track = int(m.group(1))
        pick = self.pick_robot(track, offset=int(query.get("offset", ["0"])[0] or 0))
        if not pick:
            self.note(f"   no robot opponent for track {track}")
            return None
        self.note(f"   robot for track {track}: {self.rider_name(pick[0])} {pick[3]} ms (content {pick[1]})")
        return self.robot_reply(pick, track)

    def mission_ghost(self, query):
        """match/v1/robot_v2?track_name=&score=&range=: an opponent near a target score_value."""
        m = re.search(r"(\d+)$", query.get("track_name", [""])[0])
        if not m:
            return None
        track, score = int(m.group(1)), int(query.get("score", ["0"])[0] or 0)
        # score_value = 360000000 - time - faults * 3600000; a fault-free target time of the same score
        target = 360000000 - score if 0 < score <= 360000000 else None
        pick = self.pick_robot(track, target_ms=target)
        if not pick:
            self.note(f"   no mission ghost for track {track}")
            return None
        self.note(f"   mission ghost for track {track} (score {score}): {self.rider_name(pick[0])} {pick[3]} ms")
        return self.robot_reply(pick, track)

    def robot_replay(self, query):
        """resultservice/v1/robot_replaydata?track_id=&time=&player=: that rider's ghost bytes."""
        track = int(query.get("track_id", ["-1"])[0])
        player = query.get("player", [""])[0]
        hits = self.ghosts_for(player, track)
        if "time" in query:
            hits = [h for h in hits if h[1]["metadata"].get("drive_time") == int(query["time"][0])] or hits
        if not hits:
            return None
        return open(self.ghost_path(hits[0][0]), "rb").read()

    # Requests the original services answered that have no local equivalent (yet). Answered 404 = "nothing
    # here", which the game treats like an unreachable service; logged as "not offered" instead of UNHANDLED.
    NOT_OFFERED = re.compile(r"/public/(targeting|pvp_matches|gift|match|liveevents)/")

    def handle(self, method, path, headers, body):
        """Return (status, extra headers, body) or None if unhandled."""
        u = urlsplit(path)
        p, query = u.path, parse_qs(u.query)
        m = re.fullmatch(r"/public/playerstats/v1/ranking/([^/]+)", p)
        if method == "GET" and m:
            return 200, {}, self.leaderboard(m.group(1), query)
        m = re.fullmatch(r"/public/playerstats/v1/stats/([^/]+)", p)
        if method == "GET" and m:
            return 200, {}, {"statboard": m.group(1), "results": self.leaderboard(m.group(1), query)["results"]}
        if method == "POST" and p == "/public/playerstats/v1/stats/" + GLOBAL_BOARD:
            changed = any([self.submit_global(up) for up in self.parse_updates(body)])
            return 200, {}, {"result": {"updated": 1 if changed else 0}}
        m = re.fullmatch(r"/public/resultservice/v1/enhancestats/([^/]+)", p)
        if method == "POST" and m and m.group(1) == "batch_update":
            done = []
            for up in self.parse_updates(body):
                name = up.get("track_name")
                if name:
                    self.submit(name, up)
                    done.append({"track_name": name})
            return 200, {}, {"status": done}
        if method == "POST" and m:
            improved = any([self.submit(m.group(1), up) for up in self.parse_updates(body)])
            return 200, {}, {"result": {"updated": 1 if improved else 0}}
        if method == "GET" and p == "/public/resultservice/v1/replaydata" and "track_id" in query:
            return 200, {}, self.ghost_content_for(int(query["track_id"][0]))
        if method == "POST" and p == "/public/resultservice/v1/replay_id":
            return 200, {}, self.replay_id(body)
        if method == "GET" and p == "/public/userstorage/v2/search/ghost/get_ghost" or \
                method == "GET" and p == "/public/userstorage/v2/search/ghost/get_ghost_timed":
            return 200, {}, self.search_ghost(query)
        if method == "POST" and p == "/public/userstorage/v2/content/ghost":
            status, reply = self.add_ghost(body)
            return status, {}, reply
        m = re.fullmatch(r"/public/userstorage/v2/content/ghost/(\d+)/payload", p)
        if m and method == "GET":
            g = self.store["ghosts"].get(m.group(1))
            if g and g.get("payload", True):
                return 200, {}, open(self.ghost_path(m.group(1)), "rb").read()
        if m and method == "PUT":
            status, reply = self.put_ghost_payload(m.group(1), body)
            return status, {}, reply
        m = re.fullmatch(r"/public/userstorage/v2/content/ghost/(\d+)", p)
        if m and method == "PUT":
            status, reply = self.put_ghost_metadata(m.group(1), body)
            return status, {}, reply
        if method == "GET" and p == "/public/match/v1/robot":
            reply = self.robot(query)
            if reply:
                return 200, {}, reply
        if method == "GET" and p == "/public/match/v1/robot_v2":
            reply = self.mission_ghost(query)
            if reply:
                return 200, {}, reply
        if method == "GET" and p == "/public/resultservice/v1/robot_replaydata":
            data = self.robot_replay(query)
            if data:
                return 200, {}, data
        if method == "POST" and p == "/public/liveevents/v1/weekly_track_system/basic_info":
            return 200, {}, {}  # outfit data: any 200 ends the game's 10x retry
        m = re.fullmatch(r"/avatars/(?:([0-9a-fA-F-]{36})/default|fallback)_146_146\.png", p)
        if method == "GET" and m:
            name = (m.group(1) or "fallback") + ".png"
            for d in (self.avatars, os.path.join(self.data_dir, "avatars")):
                if d and os.path.isfile(os.path.join(d, name)):
                    return 200, {}, open(os.path.join(d, name), "rb").read()
            if m.group(1) in self.community_avatars:
                return 200, {}, open(self.community_avatars[m.group(1)], "rb").read()
        if method == "GET" and p == "/v1/profiles":
            return 200, {}, self.profiles(query)
        m = re.fullmatch(r"/v1/profiles/([0-9a-fA-F-]{36})", p)
        if method == "GET" and m:  # OnlineUbiservices::getPlayerProfile (robots): one profile object
            i = m.group(1)
            return 200, {}, {"profileId": i, "userId": i, "idOnPlatform": i, "platformType": "uplay",
                             "nameOnPlatform": self.rider_name(i)}
        if method == "GET" and re.fullmatch(r"/v1/applications/[^/]+/configuration", p):
            return 200, {}, {"configuration": {"sandboxes": [
                {"name": GAME_SERVER_SANDBOX, "friendlyName": GAME_SERVER_SANDBOX, "url": self.base}]}}
        if method == "GET" and p == "/profile/":
            return 200, {"Server-Time": "%.3f" % time.time()}, {}
        if p in ("/v2/profiles/sessions", "/v1/profiles/sessions") and method in ("POST", "PUT"):
            new = requested_name(headers)
            if new and not self.fixed_name:
                with self.lock:
                    self.store["player_name"] = new
                    self.save_store()
                self.note(f"   name changed to {new}")
            sess = self.session()
            self.note(f"   login as {sess['nameOnPlatform']}")
            return 200, {}, sess
        if self.NOT_OFFERED.match(p):
            return 404, {"X-Local": "not-offered"}, {"errorCode": 404, "message": "not offered by the local server"}
        return None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    services = None

    def log_message(self, fmt, *args):
        pass

    def _serve(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        s = self.services
        interesting = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "ubi-appid", "ubi-sessionid", "content-type")}
        try:
            result = s.handle(self.command, self.path, self.headers, body)
        except Exception as e:  # keep serving; report the bug
            s.note(f"   ERROR {type(e).__name__}: {e}")
            result = (500, {}, {"errorCode": 500, "message": "local server error"})
        status = result[0] if result else 404
        tag = "" if result else " UNHANDLED"
        if result and result[1].pop("X-Local", None):
            tag, interesting = " not offered", {}
        shown = body[:300] if not body.startswith(b"{") else body[:2000]
        s.note(f"{self.command} {self.path} -> {status}{tag} {interesting if interesting else ''}"
               + (f" body={shown!r}" if body and not (self.command == "PUT" and "payload" in self.path) else
                  f" body=<{len(body)} bytes>" if body else ""))
        if result:
            _, extra, payload = result
        else:
            extra, payload = {}, {"errorCode": 404, "message": "not implemented by local server", "httpCode": 404}
        data = payload if isinstance(payload, bytes) else json.dumps(payload, separators=(",", ":")).encode()  # compact: the login library strstr()s for "environment":"Prod"
        self.send_response(status)
        ctype = "application/json" if not isinstance(payload, bytes) else \
            "image/png" if payload[:4] == b"\x89PNG" else "application/octet-stream"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = _serve


def main():
    container = opt("--container", DEFAULT_CONTAINER)
    port = int(opt("--port", "7979"))
    services = Services(container, port, opt("--profile-id"), opt("--name"), opt("--log"), opt("--avatars"))
    data = opt("--data")
    if not data:  # same place as the in-app server: Documents/LocalServices (move a store left in Library once)
        data, old = os.path.join(container, "Documents", "LocalServices"), os.path.join(container, "Library", "LocalServices")
        if not os.path.exists(data) and os.path.isdir(old):
            os.rename(old, data)
    services.load_store(data, opt("--community"))
    Handler.services = services
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    services.note(f"listening on {services.base} for {services.name} ({services.profile_id}); container {container}")
    server.serve_forever()


if __name__ == "__main__":
    main()
