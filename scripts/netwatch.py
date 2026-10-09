"""Watch the running game's network sockets and report every connection that is not loopback.

Usage: python3 -I netwatch.py [--process TrialsFrontier] [--interval 0.3] [--log file]

Polls `lsof` (no root needed for your own processes) and prints each new socket once. Lines whose remote end is
not 127.0.0.1/::1 are marked LEAK. DNS lookups happen inside mDNSResponder and are not visible here; the
local-services DNS guard blocks them in the game itself (getaddrinfo answers only "127.0.0.1").
"""
import subprocess
import sys
import time


def opt(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        val = sys.argv[i + 1]
        del sys.argv[i:i + 2]
        return val
    return default


proc, interval, log_path = opt("--process", "TrialsFrontier"), float(opt("--interval", "0.3")), opt("--log")
log = open(log_path, "a", buffering=1) if log_path else None
seen, pid = set(), None


def say(line):
    line = time.strftime("%H:%M:%S ") + line
    print(line, flush=True)
    if log:
        log.write(line + "\n")


say(f"watching process '{proc}'")
while True:
    pids = subprocess.run(["pgrep", "-x", proc], capture_output=True, text=True).stdout.split()
    if not pids:
        if pid:
            say(f"process {pid} exited")
            pid = None
        time.sleep(1)
        continue
    if pids[0] != pid:
        pid = pids[0]
        say(f"process {pid} found")
    out = subprocess.run(["lsof", "-nP", "-a", "-p", pid, "-i"], capture_output=True, text=True).stdout
    for line in out.splitlines()[1:]:
        cols = line.split()
        name = " ".join(cols[8:])
        key = (pid, cols[4], name)
        if key in seen:
            continue
        seen.add(key)
        remote = name.split("->")[1].split()[0] if "->" in name else ""
        host = remote.rsplit(":", 1)[0].strip("[]")
        leak = remote and host not in ("127.0.0.1", "::1", "localhost")
        say(f"{'LEAK ' if leak else ''}{cols[4]} {name}")
    time.sleep(interval)
