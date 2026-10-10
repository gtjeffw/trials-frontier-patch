"""Check that the native local services (inapp/, built as tfserver) answer exactly like server/local_services.py.

Usage: python3 -I tests/test_parity.py <tfserver binary> <game Documents dir to copy (player.bin, ghost_*, robot_*)>

Both servers get a copy of the same Documents and an empty store, receive the same scripted requests (login,
leaderboards, result submit, ghost search/download/upload/refusal, avatars, quiet and unhandled routes), and must give
the same status codes and bodies (JSON compared as data, timestamps ignored; binary byte for byte). At the end the two
stores must be equal. Uses the player's own data, so nothing private is kept in the repository.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PY_SERVER = os.path.join(HERE, "..", "server", "local_services.py")
TIME_KEYS = {"serverTime", "expiration"}


def call(port, method, path, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def normal(data):
    try:
        obj = json.loads(re.sub(rb"127\.0\.0\.1:798[23]", b"127.0.0.1:PORT", data))  # the two servers' own ports
    except ValueError:
        return data
    def strip(o):
        if isinstance(o, dict):
            return {k: strip(v) for k, v in o.items() if k not in TIME_KEYS}
        if isinstance(o, list):
            return [strip(v) for v in o]
        return o
    return strip(obj)


def wait(port):
    for _ in range(100):
        try:
            if call(port, "GET", "/v1/applications/x/configuration")[0] == 200:
                return
        except OSError:
            pass
        time.sleep(0.2)
    sys.exit(f"server on {port} did not start")


def main():
    tfserver, documents = sys.argv[1:3]
    work = tempfile.mkdtemp(prefix="tf-parity-")
    docs = os.path.join(work, "Data", "Documents")
    os.makedirs(docs)
    for f in os.listdir(documents):
        if f == "player.bin" or re.fullmatch(r"(ghost_[0-9a-f]{8}_\d+\.bin|robot_(ghost|image)-.*\.robot)", f):
            shutil.copy(os.path.join(documents, f), docs)
    procs = [subprocess.Popen([sys.executable, "-I", PY_SERVER, "--container", os.path.join(work, "Data"),
                               "--data", os.path.join(work, "store-py"), "--port", "7982"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT),
             subprocess.Popen([tfserver, "--documents", docs, "--data", os.path.join(work, "store-native"), "--port", "7983"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)]
    try:
        wait(7982)
        wait(7983)
        profile = json.loads(call(7982, "POST", "/v2/profiles/sessions", b"{}")[2])["profileId"]
        store = json.load(open(os.path.join(work, "store-py", "store.json")))
        own = sorted((g["track_id"], int(c)) for c, g in store["ghosts"].items() if g["profile"] == profile)
        robot = next((g, c) for c, g in sorted(store["ghosts"].items()) if g["profile"] != profile)
        track, own_cid = own[len(own) // 2]
        own_ms = store["ghosts"][str(own_cid)]["metadata"]["drive_time"]
        ghost_file = next(f for f in os.listdir(docs) if f.startswith("ghost_") and f.endswith(f"_{track}.bin"))
        ghost_bytes = open(os.path.join(docs, ghost_file), "rb").read()
        rid = robot[0]["profile"]
        rtrack = robot[0]["track_id"]
        others = {g["track_id"] for g in store["ghosts"].values() if g["profile"] != profile}
        own_only = next((t for t, _ in own if t not in others and t & 0xFFFF not in {o & 0xFFFF for o in others}), track)
        steps = [
            ("GET", f"/public/match/v1/robot?track_name=track{rtrack}&range=1&offset=0", None),
            ("GET", f"/public/match/v1/robot?track_name=track{rtrack}&range=1&offset=1", None),
            ("GET", f"/public/match/v1/robot?track_name=track{own_only}&range=1&offset=0", None),
            ("GET", "/public/match/v1/robot?track_name=track65432&range=1&offset=0", None),
            ("GET", f"/public/match/v1/robot_v2?track_name=track{rtrack}&score=359980000&range=1", None),
            ("GET", "/public/resultservice/v1/robot_replaydata?track_id=%d&time=ROBOT_TIME&player=ROBOT_PLAYER" % rtrack, None),
            ("GET", "/v1/applications/4b8b5f28-3561-4195-9dc8-c450aca960ae/configuration", None),
            ("POST", "/v2/profiles/sessions", b"{}"),
            ("PUT", "/v1/profiles/sessions", b"{}"),
            ("GET", f"/public/playerstats/v1/ranking/track{track}?around={profile},20", None),
            ("GET", f"/public/playerstats/v1/ranking/track{track}?players={profile}", None),
            ("GET", f"/public/playerstats/v1/ranking/track{track}?range=1,3", None),
            ("GET", f"/public/playerstats/v1/ranking/track{robot[0]['track_id']}?around={profile},20", None),
            ("GET", f"/public/playerstats/v1/stats/track{track}?players={profile}", None),
            ("GET", f"/public/playerstats/v1/ranking/global_stats?around={profile},20", None),
            ("GET", f"/v1/profiles?profileId={profile},{rid},00000000-0000-0000-0000-000000000000", None),
            ("GET", f"/v1/profiles/{rid}", None),
            ("GET", f"/v1/profiles/{profile}", None),
            ("POST", "/public/resultservice/v1/replay_id", json.dumps({"profile_id": profile, "track_name": f"track{track}",
                                                                       "drive_time": own_ms, "faults": 0, "bike": 1}).encode()),
            ("POST", "/public/resultservice/v1/replay_id", json.dumps({"profile_id": rid, "track_name": f"track{robot[0]['track_id']}",
                                                                       "drive_time": 1, "faults": 0, "bike": 0}).encode()),
            ("GET", f"/public/resultservice/v1/replaydata?track_id={track}", None),
            ("GET", "/public/resultservice/v1/replaydata?track_id=999999", None),
            ("GET", f"/public/userstorage/v2/search/ghost/get_ghost?track_id={track}&players={profile}&limit=1", None),
            ("GET", f"/public/userstorage/v2/search/ghost/get_ghost_timed?track_id={track}&players={profile}&drive_time={own_ms}&limit=1", None),
            ("GET", f"/public/userstorage/v2/content/ghost/{own_cid}/payload", None),
            ("GET", f"/public/userstorage/v2/content/ghost/{robot[1]}/payload", None),
            ("POST", f"/public/resultservice/v1/enhancestats/track{track}",
             b'{"updates": [ {"stats": { "data": 512,"drivetime": %d, "score_value": 1,"upgrades": 3,"submittime": 0 }}],"checksum":"X" }' % (own_ms + 5000)),
            ("POST", "/public/resultservice/v1/enhancestats/track65000",
             b'{"updates": [ {"stats": { "data": 768,"drivetime": 12345, "score_value": 1,"upgrades": 3,"submittime": 0 }}],"checksum":"X" }'),
            ("POST", "/public/resultservice/v1/enhancestats/batch_update",
             b'{"updates": [ {"stats": { "data": 768,"drivetime": 12000 },"track_name":"track65000"}, {"stats": { "data": 768,"drivetime": 99999 },"track_name":"track65001"}]}'),
            ("GET", f"/public/playerstats/v1/ranking/track65000?around={profile},20", None),
            ("POST", "/public/userstorage/v2/content/ghost",
             b'{ "metadata" : {"track_id": %d, "drive_time": %d,"checksum": 5, "version":79001}}' % (track, own_ms + 1000)),
            ("POST", "/public/userstorage/v2/content/ghost",
             b'{ "metadata" : {"track_id": %d, "drive_time": %d,"checksum": 5, "version":79001}}' % (track, own_ms)),
            ("PUT", "/public/userstorage/v2/content/ghost/NEWID/payload", ghost_bytes),
            ("PUT", "/public/userstorage/v2/content/ghost/NEWID", b'{ "metadata" : {"drive_time": %d,"checksum": 7, "version":79001}}' % own_ms),
            ("PUT", f"/public/userstorage/v2/content/ghost/{robot[1]}/payload", ghost_bytes),
            ("GET", f"/public/resultservice/v1/replaydata?track_id={track}", None),
            ("GET", "/public/userstorage/v2/content/ghost/NEWID/payload", None),
            ("GET", f"/avatars/{rid}/default_146_146.png", None),
            ("GET", "/avatars/fallback_146_146.png", None),
            ("POST", "/public/liveevents/v1/weekly_track_system/basic_info", b'{"additional_retry":256}'),
            ("GET", "/public/gift/v1/gifts", None),
            ("GET", "/public/nothing/here", None),
        ]
        failures, new_id, robot_reply = 0, None, {}
        for method, path, body in steps:
            path = path.replace("NEWID", str(new_id))
            path = path.replace("ROBOT_TIME", str(robot_reply.get("drivetime"))).replace("ROBOT_PLAYER", str(robot_reply.get("player")))
            a, b = call(7982, method, path, body), call(7983, method, path, body)
            same = a[0] == b[0] and normal(a[2]) == normal(b[2])
            if "/match/v1/robot?" in path and a[0] == 200 and not robot_reply:
                robot_reply = normal(a[2])
            if "contentId" in str(normal(a[2])) and method == "POST" and a[0] == 200:
                new_id = normal(a[2])["contentId"]
            print(f"{'ok  ' if same else 'DIFF'} {a[0]} {method} {path[:90]}")
            if not same:
                failures += 1
                print("   python:", str(normal(a[2]))[:300])
                print("   native:", str(normal(b[2]))[:300])
        time_py = call(7982, "GET", "/profile/?epoch=1")[1].get("Server-Time")
        time_na = call(7983, "GET", "/profile/?epoch=1")[1].get("Server-Time")
        print(f"{'ok  ' if time_py and time_na else 'DIFF'} Server-Time header: {time_py} / {time_na}")
        failures += not (time_py and time_na)
        sp = json.load(open(os.path.join(work, "store-py", "store.json")))
        sn = json.load(open(os.path.join(work, "store-native", "store.json")))
        same_store = sp == sn
        print(f"{'ok  ' if same_store else 'DIFF'} stores equal ({len(sp['ghosts'])} ghosts, "
              f"{sum(len(b) for b in sp['results'].values())} results)")
        if not same_store:
            failures += 1
            for k in sorted(set(sp) | set(sn)):
                if sp.get(k) != sn.get(k):
                    print("   differs:", k)
        print("PASS" if not failures else f"FAIL ({failures})")
        return 1 if failures else 0
    finally:
        for p in procs:
            p.terminate()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
