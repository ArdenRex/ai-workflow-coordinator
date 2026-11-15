"""Outbound call limiter for one connection (Step 10.6).

A sliding one-minute window per connector instance (instances are cached per credential, see WorkspaceConnectors). When the window is
full the call is refused locally with a rate-limited error and NO request is made, so a runaway agent or workflow cannot hammer a
customer's CRM, mailbox or Slack. Counts logical requests (a retry of one request is not counted twice). 0 disables the limit.
In-process only: with several server processes each has its own window, so the effective ceiling is per process.
"""
import math
import threading
import time
from collections import deque
from typing import Callable, Deque

from app.connectors.errors import ConnectorRateLimitedError

WINDOW_SECONDS = 60.0


class CallLimiter:
    def __init__(self, max_calls: int, *, window: float = WINDOW_SECONDS, clock: Callable[[], float] = time.monotonic):
        self._max, self._window, self._clock = max_calls, window, clock
        self._stamps: Deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        if self._max <= 0:
            return
        with self._lock:
            now = self._clock()
            while self._stamps and now - self._stamps[0] >= self._window:
                self._stamps.popleft()
            if len(self._stamps) >= self._max:
                raise ConnectorRateLimitedError(retry_after=max(1, math.ceil(self._window - (now - self._stamps[0]))))
            self._stamps.append(now)
