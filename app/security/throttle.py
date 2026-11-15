"""In-process sliding-window throttle for authentication endpoints (14.1).

- Failed logins are counted per (email, client address) and per email alone; a login past either limit gets 429 + Retry-After
  BEFORE any password is checked, so a locked key cannot be used to test guesses, and the answer does not depend on whether the account exists.
- Every request to the auth endpoints is also counted per client address.
- A successful login clears that (email, address) failure history only; the email-wide history keeps counting.
- Memory is bounded: at most MAX_KEYS keys are kept (the stalest are dropped first), so spraying random emails cannot grow it without limit.
LIMITS: state lives in this process. With several workers or hosts each has its own counters, so the effective limit is multiplied;
a shared store (Redis or the database) is needed for exact limits (listed for Step 15). The client address is the direct peer unless
TRUSTED_PROXY_COUNT is set (app/security/clientip.py); behind a proxy without it, all users share the proxy's address.
"""
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional, Tuple

MAX_KEYS = 10000


class Throttle:
    def __init__(self, *, max_failures: int, window_seconds: int, max_requests_per_minute: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.max_rpm = max_requests_per_minute
        self.clock = clock
        self._hits: Dict[Tuple[str, ...], Deque[float]] = {}

    # --------------------------------------------------------------- internals
    def _prune(self, key: Tuple[str, ...], window: int) -> Deque[float]:
        now = self.clock()
        q = self._hits.get(key)
        if q is None:
            if len(self._hits) >= MAX_KEYS:
                stalest = min(self._hits, key=lambda k: self._hits[k][-1] if self._hits[k] else 0.0)
                del self._hits[stalest]
            q = self._hits[key] = deque()
        while q and now - q[0] >= window:
            q.popleft()
        return q

    def _retry_after(self, q: Deque[float], window: int) -> int:
        return max(1, int(window - (self.clock() - q[0])) + 1) if q else 1

    # --------------------------------------------------------------- public
    def check_request(self, ip: str) -> Optional[int]:
        """Count one request from this address. Returns seconds to wait if over the per-minute limit, else None."""
        if self.max_rpm <= 0:
            return None
        q = self._prune(("ip", ip), 60)
        if len(q) >= self.max_rpm:
            return self._retry_after(q, 60)
        q.append(self.clock())
        return None

    def check_login(self, email: str, ip: str) -> Optional[int]:
        """Seconds to wait if this email (from this address, or from anywhere) has too many recent failures, else None."""
        if self.max_failures <= 0:
            return None
        for key, limit in ((("fail", email, ip), self.max_failures), (("fail", email), self.max_failures * 4)):
            q = self._prune(key, self.window)
            if len(q) >= limit:
                return self._retry_after(q, self.window)
        return None

    def record_failure(self, email: str, ip: str) -> None:
        if self.max_failures <= 0:
            return
        now = self.clock()
        self._prune(("fail", email, ip), self.window).append(now)
        self._prune(("fail", email), self.window).append(now)

    def record_success(self, email: str, ip: str) -> None:
        self._hits.pop(("fail", email, ip), None)
