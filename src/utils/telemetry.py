"""In-memory bounded log of recent pipeline runs (telemetry)."""

import threading


class RunLog:
    """Ring buffer of completed agent runs, newest last."""

    def __init__(self, maxlen: int = 100):
        self.maxlen = maxlen
        self._runs: list[dict] = []
        self._lock = threading.Lock()

    def push(self, run: dict) -> None:
        with self._lock:
            self._runs.append(run)
            if len(self._runs) > self.maxlen:
                del self._runs[: len(self._runs) - self.maxlen]

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._runs)

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()


run_log = RunLog()
