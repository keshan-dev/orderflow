import threading

from orderflow_common.background import PeriodicTask


def test_task_runs_repeatedly_and_survives_errors():
    calls: list[int] = []
    done = threading.Event()

    def work():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("first run fails")
        if len(calls) >= 3:
            done.set()

    task = PeriodicTask("test", 0.01, work)
    task.start()
    assert done.wait(5), "task stopped after an error"
    task.stop()
    stopped_at = len(calls)
    threading.Event().wait(0.05)
    assert len(calls) == stopped_at
