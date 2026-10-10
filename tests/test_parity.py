"""Check that the native local services (inapp/, built as tfserver) answer exactly like server/local_services.py.

Usage: python3 -I tests/test_parity.py <tfserver binary> <game Documents dir to copy (player.bin, ghost_*, robot_*)>

Both servers get a copy of the same Documents and an empty store, receive the same scripted requests (login,
leaderboards, result submit, ghost search/download/upload/refusal, avatars, quiet and unhandled routes), and must give
the same status codes and bodies (JSON compared as data, timestamps ignored; binary byte for byte). At the end the two
stores must be equal. A community layer (scripts/community.py build from a bundle of a made-up rider who also
carries the downloaded opponents) is overlaid by both: its rider, results, ghosts and avatar must be served alike,
and neither store may keep anything of it; an older store's imported world records are dropped. Then a new player: empty Documents (no save yet), each server makes up a profile id and keeps
it, the name is "Rider" until a save appears and then the save's. Uses the player's own data, so nothing private is
kept in the repository.
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
SCRIPTS = os.path.join(HERE, "..", "scripts")
FAKE_HASH = "ABCDEF01"
LEGACY = {"results": {"track1": {"0f0e0d0c-0000-5000-8000-000000000001": {
              "drivetime": 1, "data": 0, "upgrades": 0, "submittime": 0, "score_value": 359999999, "extradata": 0,
              "source": "wr2019"}}},
          "riders": {"0f0e0d0c-0000-5000-8000-000000000001": {"name": "old world record", "source": "wr2019"}},
          "ghosts": {}, "next_id": 1000, "world_records_imported": "wrrider.json"}
TIME_KEYS = {"serverTime", "expiration"}


def call(port, method, path, body=None, headers=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method, headers=headers or {})
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


def claimed_id(sha):
    return str(__import__("uuid").uuid5(__import__("uuid").NAMESPACE_URL, "trials-frontier-rider:" + sha))


def make_layer(work, docs):
    """A community layer from four bundles of the test Documents: "Parity Rider" (made-up identity, avatar, all the
    downloaded opponents), "Parity Twin" (a different rider with the same 32-bit hash), "Player Hash Twin" (a
    different rider whose hash equals the player's) and the player's own bundle (must be skipped)."""
    home = os.path.join(work, "community-home")
    env = dict(os.environ, TF_COMMUNITY_HOME=home)
    community = [sys.executable, "-I", os.path.join(SCRIPTS, "community.py")]
    subprocess.run(community + ["disable", "gtjeffw/trials-frontier-ghosts-jayuph"], env=env, check=True, stdout=subprocess.DEVNULL)
    own = os.path.join(work, "bundle-own")
    subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "ghost_bundle.py"), "export", docs, own,
                    "--include-others"], check=True, stdout=subprocess.DEVNULL)
    m_own = json.load(open(os.path.join(own, "trials-frontier-bundle.json")))
    png = b"\x89PNG\r\n\x1a\n" + b"parity" * 10
    variants = {"bundle": ("Parity Rider", FAKE_HASH, "0" * 64, True),
                "bundle-twin": ("Parity Twin", FAKE_HASH, "1" * 64, False),
                "bundle-player-hash": ("Player Hash Twin", m_own["rider"]["game_hash"], "2" * 64, False)}
    made = {}
    for folder, (name, h, sha, others) in variants.items():
        b = os.path.join(work, folder)
        shutil.copytree(own, b)
        m = json.load(open(os.path.join(b, "trials-frontier-bundle.json")))
        m["rider"].update(name=name, game_hash=h, profile_sha256=sha)
        if name == "Parity Rider":
            open(os.path.join(b, "avatar.png"), "wb").write(png)
            m["rider"]["avatar"] = {"file": "avatar.png", "sha256": __import__("hashlib").sha256(png).hexdigest()}
        if not others:
            m.pop("others", None)
        json.dump(m, open(os.path.join(b, "trials-frontier-bundle.json"), "w"))
        made[name] = claimed_id(sha)
    for folder in ["bundle-own"] + list(variants):
        subprocess.run(community + ["add", os.path.join(work, folder)], env=env, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(community + ["sync"], env=env, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(community + ["build"], env=env, check=True, stdout=subprocess.DEVNULL)
    made["own"] = claimed_id(m_own["rider"]["profile_sha256"])
    return os.path.join(home, "layer"), made


def start(tfserver, work, docs, layer=None):
    extra = ["--community", layer] if layer else []
    procs = [subprocess.Popen([sys.executable, "-I", PY_SERVER, "--container", os.path.join(work, "Data"),
                               "--data", os.path.join(work, "store-py"), "--port", "7982"] + extra,
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT),
             subprocess.Popen([tfserver, "--documents", docs, "--data", os.path.join(work, "store-native"), "--port", "7983"] + extra,
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)]
    wait(7982)
    wait(7983)
    return procs


def stop(procs):
    for p in procs:
        p.terminate()
        p.wait()


def new_player(tfserver, documents):
    """No save yet: a made-up profile id that survives a restart, "Rider", then the name from the save once there."""
    work = tempfile.mkdtemp(prefix="tf-parity-new-")
    docs = os.path.join(work, "Data", "Documents")
    os.makedirs(docs)
    failures, ids = 0, {}
    try:
        for round_ in (1, 2):
            procs = start(tfserver, work, docs)
            try:
                for port in (7982, 7983):
                    sess = json.loads(call(port, "POST", "/v2/profiles/sessions", b"{}")[2])
                    pid = sess["profileId"]
                    store = json.load(open(os.path.join(work, "store-py" if port == 7982 else "store-native", "store.json")))
                    ok = (re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}", pid) and
                          sess["nameOnPlatform"] == "Rider" and store.get("new_player_profile") == pid and
                          ids.setdefault(port, pid) == pid)
                    print(f"{'ok  ' if ok else 'DIFF'} new player, start {round_}, port {port}: {sess['nameOnPlatform']} {pid}")
                    failures += not ok
                if round_ == 2:
                    body = b'{"updates": [ {"stats": { "data": 768,"drivetime": 12345, "score_value": 1,"upgrades": 3,"submittime": 0 }}],"checksum":"X" }'
                    replies = []
                    for port in (7982, 7983):
                        call(port, "POST", "/public/resultservice/v1/enhancestats/track65000", body)
                        r = call(port, "GET", f"/public/playerstats/v1/ranking/track65000?around={ids[port]},20")
                        replies.append(normal(r[2].replace(ids[port].encode(), b"PID")))
                    same = replies[0] == replies[1]
                    print(f"{'ok  ' if same else 'DIFF'} new player's first result")
                    failures += not same
                    shutil.copy(os.path.join(documents, "player.bin"), docs)
                    names = [json.loads(call(port, "POST", "/v2/profiles/sessions", b"{}")[2])["nameOnPlatform"]
                             for port in (7982, 7983)]
                    ok = names[0] == names[1] != "Rider"
                    print(f"{'ok  ' if ok else 'DIFF'} name from the save once it exists")
                    failures += not ok
            finally:
                stop(procs)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return failures


def main():
    tfserver, documents = sys.argv[1:3]
    work = tempfile.mkdtemp(prefix="tf-parity-")
    docs = os.path.join(work, "Data", "Documents")
    os.makedirs(docs)
    for f in os.listdir(documents):
        if f == "player.bin" or re.fullmatch(r"(ghost_[0-9a-f]{8}_\d+\.bin|robot_(ghost|image)-.*\.robot)", f):
            shutil.copy(os.path.join(documents, f), docs)
    layer, made = make_layer(work, docs)
    for d in ("store-py", "store-native"):  # a store from an older version, with imported world records
        os.makedirs(os.path.join(work, d))
        json.dump(LEGACY, open(os.path.join(work, d, "store.json"), "w"))
    procs = start(tfserver, work, docs, layer)
    try:
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
        fake_rid = made["Parity Rider"]
        layer_json = json.load(open(os.path.join(layer, "community.json")))
        fake_cid, fake_ghost = next((c, g) for c, g in sorted(layer_json["ghosts"].items()) if g["profile"] == fake_rid)
        fake_track = fake_ghost["track_id"]
        steps = [
            ("GET", f"/public/playerstats/v1/ranking/track{fake_track}?range=1,50", None),
            ("GET", f"/v1/profiles/{fake_rid}", None),
            ("GET", f"/v1/profiles?profileId={fake_rid},{rid}", None),
            ("GET", f"/avatars/{fake_rid}/default_146_146.png", None),
            ("GET", f"/public/userstorage/v2/search/ghost/get_ghost?track_id={fake_track}&players={fake_rid}&limit=1", None),
            ("GET", f"/public/userstorage/v2/content/ghost/{fake_cid}/payload", None),
            ("GET", f"/public/match/v1/robot?track_name=track{fake_track}&range=1&offset=0", None),
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
            ("POST", "/public/playerstats/v1/stats/global_stats",
             b'{"updates": [ {"stats": {"data": 256,"drivetime": 28516, "global_score": 5.378462,"upgrades": 0,"submittime": 0 }}]}'),
            ("POST", "/public/playerstats/v1/stats/global_stats",
             b'{"updates": [ {"stats": {"data": 256,"drivetime": 28516, "global_score": 5.378462,"upgrades": 0,"submittime": 0 }}]}'),
            ("POST", "/public/playerstats/v1/stats/global_stats",
             b'{"updates": [ {"stats": {"data": 256,"drivetime": 26110, "global_score": 14.883273,"upgrades": 128,"submittime": 0 }}]}'),
            ("GET", f"/public/playerstats/v1/ranking/global_stats?around={profile},20", None),
            ("GET", f"/public/playerstats/v1/ranking/global_stats?players={profile}", None),
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
        # the game's change-name request (tutorial / options): the name inside the login token is adopted
        b64 = lambda t: __import__("base64").b64encode(t.encode()).decode()
        rename = {"Authorization": "UbiMobile_v1 t=" + b64("acct-1:secret:" + b64("Parity Name"))}
        plain = {"Authorization": "UbiMobile_v1 t=" + b64("acct-1:secret:" + b64("Rider"))}  # library echoes the placeholder
        names = []
        for port in (7982, 7983):
            names.append([json.loads(call(port, "POST", "/v2/profiles/sessions", b"{}", h)[2])["nameOnPlatform"]
                          for h in (plain, rename, plain, None)])
        before = names[0][0]
        ok = names[0] == names[1] and names[0][1:] == ["Parity Name"] * 3 and before != "Parity Name"
        print(f"{'ok  ' if ok else 'DIFF'} change-name request adopted and kept: {names[0]} / {names[1]}")
        failures += not ok
        # identities: same 32-bit hash = still different riders; the player's hash alone does not make a rider "me"
        ids = {}
        for port in (7982, 7983):
            names = {e["profileId"]: e["nameOnPlatform"] for e in json.loads(call(port, "GET", "/v1/profiles?profileId="
                     + ",".join(made.values()))[2])["profiles"]}
            board = json.loads(call(port, "GET", f"/public/playerstats/v1/ranking/track{fake_track}?range=1,1000")[2])
            ids[port] = (sorted(names[made[n]] for n in ("Parity Rider", "Parity Twin", "Player Hash Twin")),
                         {r["player"] for r in board["results"]} & set(made.values()))
        ok = all(v == (["Parity Rider", "Parity Twin", "Player Hash Twin"],
                       {made["Parity Rider"], made["Parity Twin"], made["Player Hash Twin"]}) for v in ids.values())
        print(f"{'ok  ' if ok else 'DIFF'} identities: a shared 32-bit hash keeps riders apart; the player's own "
              f"bundle is skipped, a stranger with the player's hash is not")
        failures += not ok
        sp = json.load(open(os.path.join(work, "store-py", "store.json")))
        sn = json.load(open(os.path.join(work, "store-native", "store.json")))
        same_store = sp == sn
        print(f"{'ok  ' if same_store else 'DIFF'} stores equal ({len(sp['ghosts'])} ghosts, "
              f"{sum(len(b) for b in sp['results'].values())} results)")
        leaked = [k for k in sp["ghosts"] if int(k) >= 1_000_000_000] + \
            [r for r, e in sp["riders"].items() if e.get("source") in ("community", "wr2019") or r == fake_rid] + \
            [b for b, e in sp["results"].items() if fake_rid in e or any(st.get("source", "").startswith(("community", "wr2019"))
                                                                         for st in e.values())] + \
            [k for k in ("world_records_imported",) if k in sp]
        print(f"{'ok  ' if not leaked else 'DIFF'} nothing of the community layer or the old world records in the store"
              + (f": {leaked[:5]}" if leaked else ""))
        failures += bool(leaked)
        if not same_store:
            failures += 1
            for k in sorted(set(sp) | set(sn)):
                if sp.get(k) != sn.get(k):
                    print("   differs:", k)
    finally:
        stop(procs)
        shutil.rmtree(work, ignore_errors=True)
    failures += new_player(tfserver, documents)
    print("PASS" if not failures else f"FAIL ({failures})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
