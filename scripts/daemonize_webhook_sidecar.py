#!/usr/bin/env python3
"""Daemonize the webhook delivery sidecar (gateway-immune, PPID=1).

Usage: python3 daemonize_webhook_sidecar.py
Env: STDB_URL / STDB_DB / STDB_TOKEN are read by the sidecar itself.
"""
import os
import sys

BIN = "/home/hindsight/spacetime-memory/server/webhook-sidecar/target/release/webhook-sidecar"
PIDFILE = "/tmp/webhook_sidecar.pid"
LOGFILE = "/tmp/webhook_sidecar.log"


def main():
    if not os.path.exists(BIN):
        print(f"sidecar binary missing: {BIN}")
        sys.exit(1)
    if os.path.exists(PIDFILE):
        try:
            old = int(open(PIDFILE).read().strip())
            os.kill(old, 0)
            print(f"sidecar already running (pid {old})")
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            pass
    if os.fork() > 0:
        sys.exit(0)
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    logfd = os.open(LOGFILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(devnull)
    os.close(logfd)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    # Sidecar reads its own env: STDB_URL/STDB_DB/STDB_TOKEN
    env = dict(os.environ)
    env["STDB_URL"] = env.get("STDB_URL", "http://127.0.0.1:3001")
    env["STDB_DB"] = env.get("STDB_DB", "spacetime-memory-v2")
    env["POLL_INTERVAL_SECS"] = env.get("POLL_INTERVAL_SECS", "5")
    env["RUST_LOG"] = env.get("RUST_LOG", "info")
    os.execvpe(BIN, [BIN], env)


if __name__ == "__main__":
    main()