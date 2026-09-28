"""In-process sliding-window rate limiter for the `/mcp` endpoint.

State lives in the worker process: with N Odoo workers the effective ceiling is
up to N times the limit. That is deliberate (no shared infrastructure).
"""
import math
import threading
import time
from collections import deque

PRUNE_EVERY = 256
PRUNE_ABOVE = 1000


class SlidingWindow:

    def __init__(self, limit=120, window=60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._buckets = {}
        self._lock = threading.Lock()
        self._calls = 0

    def check(self, key):
        """Count one request for `key`; return ``(allowed, retry_after_seconds)``."""
        now = self.clock()
        with self._lock:
            self._calls += 1
            if self._calls % PRUNE_EVERY == 0 or len(self._buckets) > PRUNE_ABOVE:
                self._prune(now)
            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False, max(1, math.ceil(bucket[0] + self.window - now))
            bucket.append(now)
            return True, 0

    def _prune(self, now):
        idle = [key for key, bucket in self._buckets.items() if not bucket or bucket[-1] <= now - self.window]
        for key in idle:
            del self._buckets[key]

    def clear(self):
        with self._lock:
            self._buckets.clear()


LIMITER = SlidingWindow()
