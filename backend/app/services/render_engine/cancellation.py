"""Bound cancellation reads in noisy compiler stdout loops."""
import time
from collections.abc import Callable


class CancellationPoll:
    """Poll immediately, then at most every interval; a true result stays true.

    ProcessWatchdog independently polls while the compiler is silent. This helper
    bounds only the redundant per-line Redis reads, without delaying the first read.
    """

    def __init__(self, check: Callable[[], bool], interval: float = 0.1):
        self.check = check
        self.interval = interval
        self.next_check = 0.0
        self.cancelled = False

    def __call__(self) -> bool:
        now = time.monotonic()
        if not self.cancelled and now >= self.next_check:
            self.cancelled = self.check()
            self.next_check = now + self.interval
        return self.cancelled
