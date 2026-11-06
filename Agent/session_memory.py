"""Short-lived server memory; no cache, files or background API requests."""
import copy
from threading import RLock, Timer


class SessionResult:
    def __init__(self, result, ttl=900):
        self._lock = RLock()
        self._result = result
        self._timer = Timer(ttl, self.clear)
        self._timer.daemon = True
        self._timer.start()

    def snapshot(self):
        with self._lock:
            return copy.deepcopy(self._result)

    def get(self, key, default=None):
        with self._lock:
            return self._result.get(key, default)

    def clear(self):
        with self._lock:
            self._result.clear()
            self._timer.cancel()
