"""Local game-services server for the `local-services` patch group (prototype, Python stdlib only).

Usage: python3 -I server/local_services.py [--container <app container Data dir>] [--port 7979]
                                           [--profile-id <uuid>] [--name <name>] [--avatars <dir>] [--log <file>]
                                           [--data <dir>]

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

Results and ghosts live in a store (--data, default <container>/Library/LocalServices: store.json + ghosts/<id>.bin),
seeded on start from the save's score table and the player's own ghost_<hash>_<leaderboard>.bin files. As with the
original service, a submitted result (resultservice/v1/enhancestats/...) is "updated" only if it beats the stored
one (fewer faults, then less time); the game uploads a ghost only after such a reply, and the store keeps one ghost
per player and leaderboard, refusing a slower one.
"""
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


def read_profile(container):
    """(profile id, name) from player.bin: name at raw offset 20 (Player+0x10), profile id at 276 (Player+0x110)."""
    _, raw = decode(open(os.path.join(container, "Documents", "player.bin"), "rb").read())
    name = raw[20:20 + 128].split(b"\0")[0].decode("utf-8", "replace")
    pid = raw[276:276 + 40].split(b"\0")[0].decode("ascii", "replace")
    return pid, name


class Services:
    def __init__(self, container, port, profile_id, name, log_path, avatars=None):
        self.container, self.port, self.avatars = container, port, avatars
        self.base = f"http://127.0.0.1:{port}"
        if not (profile_id and name):
            pid, nm = read_profile(container)
            profile_id, name = profile_id or pid, name or nm
        self.profile_id, self.name = profile_id, name
        self.ticket = "local-" + uuid.uuid5(uuid.NAMESPACE_URL, profile_id).hex
        self.log = open(log_path, "a", buffering=1) if log_path else None

    def note(self, line):
        line = time.strftime("%H:%M:%S ") + line
        print(line, flush=True)
        if self.log:
            self.log.write(line + "\n")

    def session(self):
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

    def scores(self):
        _, raw = decode(open(self.documents("player.bin"), "rb").read())
        return read_scores(raw)

    # ---- persistent store (results and ghosts), seeded from the save and its ghost files ----

    def load_store(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(os.path.join(data_dir, "ghosts"), exist_ok=True)
        self.lock = threading.RLock()
        path = os.path.join(data_dir, "store.json")
        self.store = json.load(open(path)) if os.path.exists(path) else {"results": {}, "ghosts": {}, "next_id": 1000}
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
        self.save_store()
        self.note(f"store {data_dir}: {sum(len(b) for b in self.store['results'].values())} results, "
                  f"{len(self.store['ghosts'])} ghosts ({seeded} imported now)")

    def new_id(self):
        with self.lock:
            cid = self.store["next_id"]
            self.store["next_id"] += 1
            return cid

    def ghost_path(self, cid):
        return os.path.join(self.data_dir, "ghosts", "%d.bin" % int(cid))

    def save_store(self):
        with self.lock:
            tmp = os.path.join(self.data_dir, "store.json.tmp")
            json.dump(self.store, open(tmp, "w"), indent=1)
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
        entries = sorted(self.board(name).items(), key=lambda kv: ((kv[1]["data"] & 0xFF), kv[1]["drivetime"]))
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
        return sorted(out, key=lambda x: (x[1]["track_id"] != track, x[1]["metadata"].get("drive_time") or 1 << 31))

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

    def profiles(self, query):
        ids = ",".join(query.get("profileId", [])).split(",")
        return {"profiles": [{"profileId": i, "userId": i, "idOnPlatform": i, "platformType": "uplay",
                              "nameOnPlatform": self.name if i == self.profile_id else "rider"} for i in ids if i]}

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
        if method == "POST" and p == "/public/liveevents/v1/weekly_track_system/basic_info":
            return 200, {}, {}  # outfit data: any 200 ends the game's 10x retry
        m = re.fullmatch(r"/avatars/(?:([0-9a-fA-F-]{36})/default|fallback)_146_146\.png", p)
        if method == "GET" and m and self.avatars:
            f = os.path.join(self.avatars, (m.group(1) or "fallback") + ".png")
            if os.path.isfile(f):
                return 200, {}, open(f, "rb").read()
        if method == "GET" and p == "/v1/profiles":
            return 200, {}, self.profiles(query)
        if method == "GET" and re.fullmatch(r"/v1/applications/[^/]+/configuration", p):
            return 200, {}, {"configuration": {"sandboxes": [
                {"name": GAME_SERVER_SANDBOX, "friendlyName": GAME_SERVER_SANDBOX, "url": self.base}]}}
        if method == "GET" and p == "/profile/":
            return 200, {"Server-Time": "%.3f" % time.time()}, {}
        if p in ("/v2/profiles/sessions", "/v1/profiles/sessions") and method in ("POST", "PUT"):
            return 200, {}, self.session()
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
    services.load_store(opt("--data", os.path.join(container, "Library", "LocalServices")))
    Handler.services = services
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    services.note(f"listening on {services.base} for {services.name} ({services.profile_id}); container {container}")
    server.serve_forever()


if __name__ == "__main__":
    main()
