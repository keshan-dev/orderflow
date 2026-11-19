import os
import time

from orderflow_common.heartbeat import beat, is_fresh


def test_fresh_after_beat_and_stale_later(tmp_path):
    path = str(tmp_path / "hb")
    assert not is_fresh(path)
    beat(path)
    assert is_fresh(path)
    old = time.time() - 60
    os.utime(path, (old, old))
    assert not is_fresh(path)
