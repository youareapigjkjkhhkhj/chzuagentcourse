#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: launch_detached.py <pidfile> <logfile> <cmd...>", file=sys.stderr)
        return 1

    pidfile = sys.argv[1]
    logfile = sys.argv[2]
    cmd = sys.argv[3:]

    os.makedirs(os.path.dirname(pidfile), exist_ok=True)
    os.makedirs(os.path.dirname(logfile), exist_ok=True)

    with open(logfile, "ab") as log:
        process = subprocess.Popen(
            cmd,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    with open(pidfile, "w", encoding="utf-8") as handle:
        handle.write(str(process.pid))

    print(process.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
