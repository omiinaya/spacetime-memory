#!/usr/bin/env python3
"""Daemonize a bash script via double-fork so it survives the gateway's 1800s killer.
Usage: python3 daemonize_bash.py <script.sh> <pidfile> <logfile>
"""
import os
import sys


def main():
    script = sys.argv[1]
    pidfile = sys.argv[2]
    logfile = sys.argv[3]
    if os.path.exists(pidfile):
        try:
            old = int(open(pidfile).read().strip())
            os.kill(old, 0)
            print(f"Already running (pid {old}). Exiting.")
            sys.exit(0)
        except (ProcessLookupError, ValueError):
            pass
    if os.fork() > 0:
        sys.exit(0)  # parent exits
    os.setsid()
    if os.fork() > 0:
        os._exit(0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    logfd = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(logfd, 1)
    os.dup2(logfd, 2)
    os.close(devnull)
    os.close(logfd)
    pid = os.getpid()
    with open(pidfile, "w") as f:
        f.write(str(pid))
    env = dict(os.environ)
    env["OTEL_ENABLED"] = "false"
    env["LLM_BASE_URL"] = "http://localhost:4004/v1"
    env["OPENAI_API_KEY"] = "dummy-key"
    os.execvpe("/bin/bash", ["/bin/bash", script], env)


if __name__ == "__main__":
    main()