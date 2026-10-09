"""Local game-services server for the `local-services` patch group (prototype, Python stdlib only).

Usage: python3 -I server/local_services.py [--container <app container Data dir>] [--port 7979]
                                           [--profile-id <uuid>] [--name <name>] [--log <file>]

Listens on 127.0.0.1 only. The patched game sends every request here (see docs/JOURNAL.md, "Online services probe"):
  GET  /v1/applications/<appId>/configuration   app configuration; its sandbox "triag_ip_lnch61_a_ws" names the game server
  GET  /profile/?epoch=1                        network time for the mobile login library ("Server-Time:" header)
  POST /v2/profiles/sessions                    mobile login library: create device account / get session ticket
  PUT  /v1/profiles/sessions                    ticket renewal
  .../public/...                                game server (leaderboards, ghosts)
Every request is logged; anything not handled yet is answered 404 and marked UNHANDLED so it can be implemented.
The player's profile id and name are read from the container's Documents/player.bin unless given.
"""
import json
import os
import re
import sys
import time
import uuid
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


def read_profile(container):
    """(profile id, name) from player.bin: name at raw offset 20 (Player+0x10), profile id at 276 (Player+0x110)."""
    _, raw = decode(open(os.path.join(container, "Documents", "player.bin"), "rb").read())
    name = raw[20:20 + 128].split(b"\0")[0].decode("utf-8", "replace")
    pid = raw[276:276 + 40].split(b"\0")[0].decode("ascii", "replace")
    return pid, name


class Services:
    def __init__(self, container, port, profile_id, name, log_path):
        self.container, self.port = container, port
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

    def handle(self, method, path, headers, body):
        """Return (status, extra headers, body bytes) or None if unhandled."""
        p = path.split("?")[0]
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
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream" if isinstance(payload, bytes) else "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = _serve


def main():
    container = opt("--container", DEFAULT_CONTAINER)
    port = int(opt("--port", "7979"))
    services = Services(container, port, opt("--profile-id"), opt("--name"), opt("--log"))
    Handler.services = services
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    services.note(f"listening on {services.base} for {services.name} ({services.profile_id}); container {container}")
    server.serve_forever()


if __name__ == "__main__":
    main()
