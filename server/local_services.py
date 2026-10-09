"""Local game-services server for the `local-services` patch group (prototype, Python stdlib only).

Usage: python3 -I server/local_services.py [--container <app container Data dir>] [--port 7979]
                                           [--profile-id <uuid>] [--name <name>] [--avatars <dir>] [--log <file>]

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
"""
import json
import os
import re
import struct
import sys
import threading
import time
import uuid
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
        return f[1] & 0xFF == 0xFF and (f[9] == 0 or f[9] + f[10] + f[8] * 3600000 == 360000000)
    best = None
    for start in range(0, len(raw) - 68, 4):
        n = struct.unpack_from("<I", raw, start)[0]
        if 1 <= n <= 2000 and start + 4 + n * 64 <= len(raw) and \
                all(is_record(start + 4 + i * 64) for i in range(n)) and (best is None or n > best[1]):
            best = (start, n)
    scores = {}
    if best:
        for i in range(best[1]):
            f = struct.unpack_from("<16I", raw, best[0] + 4 + i * 64)
            if f[9]:
                scores[f[0]] = (f[8], f[9], f[11])
    return scores


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
        self.replays, self.replay_lock = {}, threading.Lock()
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

    def leaderboard(self, name, query):
        """Ranking for leaderboard `name` ("track<id>", ...): the player's own best from the save."""
        m = re.search(r"(\d+)$", name)
        lb = int(m.group(1)) if m else -1
        scores = self.scores()
        hit = scores.get(lb)
        if hit is None and name.startswith("track"):
            hit = next((v for k, v in sorted(scores.items()) if k & 0xFFFF == lb), None)
        results = []
        wanted = None
        if "players" in query:
            wanted = set(",".join(query["players"]).split(","))
        if hit and (wanted is None or self.profile_id in wanted):
            faults, ms, bike = hit
            results.append({"player": self.profile_id, "rank": 1, "stats": {
                "drivetime": ms, "data": (faults & 0xFF) | ((bike & 0x3F) << 8), "upgrades": 0, "submittime": 0,
                "score_value": 360000000 - ms - faults * 3600000, "extradata": 0}})
        return {"leaderboard": name, "playerCount": len(results), "results": results}

    def ghost_files(self, track):
        prefix = "ghost_%08x_" % game_hash(self.profile_id)
        out = []
        for f in sorted(os.listdir(self.documents())):
            m = re.fullmatch(re.escape(prefix) + r"(\d+)\.bin", f)
            if m and (int(m.group(1)) == track or int(m.group(1)) & 0xFFFF == track):
                out.append(f)
        return out

    def replay_id(self, body):
        req = json.loads(body or b"{}")
        m = re.search(r"(\d+)$", str(req.get("track_name", "")))
        if req.get("profile_id") != self.profile_id or not m:
            return {"replay_id": 0}
        files = self.ghost_files(int(m.group(1)))
        if not files:
            self.note(f"   no ghost for track {m.group(1)}")
            return {"replay_id": 0}
        with self.replay_lock:
            rid = next((k for k, v in self.replays.items() if v == files[0]), None) or len(self.replays) + 1000
            self.replays[rid] = files[0]
        self.note(f"   replay {rid} = {files[0]}")
        return {"replay_id": rid}

    def profiles(self, query):
        ids = ",".join(query.get("profileId", [])).split(",")
        return {"profiles": [{"profileId": i, "userId": i, "idOnPlatform": i, "platformType": "uplay",
                              "nameOnPlatform": self.name if i == self.profile_id else "rider"} for i in ids if i]}

    def handle(self, method, path, headers, body):
        """Return (status, extra headers, body bytes) or None if unhandled."""
        u = urlsplit(path)
        p, query = u.path, parse_qs(u.query)
        m = re.fullmatch(r"/public/playerstats/v1/ranking/([^/]+)", p)
        if method == "GET" and m:
            return 200, {}, self.leaderboard(m.group(1), query)
        m = re.fullmatch(r"/public/playerstats/v1/stats/([^/]+)", p)
        if method == "GET" and m:
            board = self.leaderboard(m.group(1), query)
            return 200, {}, {"statboard": m.group(1), "results": board["results"]}
        m = re.fullmatch(r"/avatars/(?:([0-9a-fA-F-]{36})/default|fallback)_146_146\.png", p)
        if method == "GET" and m and self.avatars:
            f = os.path.join(self.avatars, (m.group(1) or "fallback") + ".png")
            if os.path.isfile(f):
                return 200, {}, open(f, "rb").read()
        if method == "GET" and p == "/v1/profiles":
            return 200, {}, self.profiles(query)
        if method == "POST" and p == "/public/resultservice/v1/replay_id":
            return 200, {}, self.replay_id(body)
        m = re.fullmatch(r"/public/userstorage/v2/content/ghost/(\d+)/payload", p)
        if method == "GET" and m and int(m.group(1)) in self.replays:
            return 200, {}, open(self.documents(self.replays[int(m.group(1))]), "rb").read()
        if method == "GET" and re.fullmatch(r"/v1/applications/[^/]+/configuration", p):
            return 200, {}, {"configuration": {"sandboxes": [
                {"name": GAME_SERVER_SANDBOX, "friendlyName": GAME_SERVER_SANDBOX, "url": self.base}]}}
        if method == "GET" and p == "/profile/":
            return 200, {"Server-Time": "%.3f" % time.time()}, {}
        if p in ("/v2/profiles/sessions", "/v1/profiles/sessions") and method in ("POST", "PUT"):
            return 200, {}, self.session()
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
        result = s.handle(self.command, self.path, self.headers, body)
        status = result[0] if result else 404
        s.note(f"{self.command} {self.path} -> {status}{'' if result else ' UNHANDLED'} {interesting}"
               + (f" body={body[:300]!r}" if body else ""))
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
    Handler.services = services
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    services.note(f"listening on {services.base} for {services.name} ({services.profile_id}); container {container}")
    server.serve_forever()


if __name__ == "__main__":
    main()
