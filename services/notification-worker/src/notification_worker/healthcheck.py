"""Container health check: the worker loop touched its heartbeat file recently.

Run: python -m notification_worker.healthcheck
"""

import os
import sys
import time

MAX_AGE_SECONDS = 30


def main() -> int:
    path = os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat")
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return 1
    return 0 if age < MAX_AGE_SECONDS else 1


if __name__ == "__main__":
    sys.exit(main())
