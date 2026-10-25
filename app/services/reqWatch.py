"""
Cheap change detection for the UI -> service request file (audit ARCH-01).

The service used to open and parse request.json about five times a second forever. This watcher only
reads the file when its modification time or size changed, and polls less often once nothing has
changed for a while. A new command after a long idle period is therefore picked up within `slow`
seconds (default 1 s) instead of 0.2 s.
"""
import json
import os
import time
from typing import Callable, Optional


class RequestWatcher:
    def __init__(self, path: str, fast: float = 0.2, slow: float = 1.0, idle_after: float = 10.0,
                 clock: Callable[[], float] = time.monotonic):
        self.path = str(path)
        self.fast, self.slow, self.idle_after = fast, slow, idle_after
        self._clock = clock
        self._signature = None
        self._last_change = clock()

    def _read(self) -> dict:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def poll(self) -> Optional[dict]:
        """Return the parsed file if it changed since the last successful read, else None."""
        try:
            st = os.stat(self.path)
        except OSError:
            return None
        signature = (st.st_mtime_ns, st.st_size)
        if signature == self._signature:
            return None
        try:
            data = self._read()
        except (OSError, ValueError):
            return None          # half-written or replaced mid-read: try again on the next poll
        if not isinstance(data, dict):
            return None
        self._signature = signature
        self._last_change = self._clock()
        return data

    def next_sleep(self) -> float:
        return self.fast if (self._clock() - self._last_change) < self.idle_after else self.slow
