"""Health checks for workers without an HTTP port.

The worker calls beat() while it works; the container health check runs
`python -m orderflow_common.heartbeat` and passes only if the file is fresh.
"""

import os
import pathlib
import sys
import time

DEFAULT_FILE = "/tmp/heartbeat"
MAX_AGE_SECONDS = 30


def beat(path: str = DEFAULT_FILE) -> None:
    pathlib.Path(path).touch()


def is_fresh(path: str = DEFAULT_FILE, max_age_seconds: float = MAX_AGE_SECONDS) -> bool:
    try:
        return time.time() - os.path.getmtime(path) < max_age_seconds
    except OSError:
        return False


def main() -> int:
    return 0 if is_fresh(os.environ.get("HEARTBEAT_FILE", DEFAULT_FILE)) else 1


if __name__ == "__main__":
    sys.exit(main())
