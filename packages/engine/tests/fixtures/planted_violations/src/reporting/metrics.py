"""Cycle 2 second half: reporting.metrics imports shipping.dispatcher."""

from src.shipping.dispatcher import Dispatcher


class Metrics:
    def record(self, event: str) -> None:
        Dispatcher()

    def summarize_complex(
        self,
        a: int,
        b: int,
        c: int,
        d: int,
        e: int,
    ) -> int:
        """High CC (>15)."""
        total = 0
        if a > 0:
            total += a
        elif a < 0:
            total -= a
        if b > 0 and c > 0:
            total += b + c
        elif b > 0 or c > 0:
            total += max(b, c)
        if d == 0:
            total *= 2
        elif d == 1:
            total *= 3
        elif d == 2:
            total *= 4
        else:
            total *= 5
        if e in (0, 1):
            total += 10
        elif e in (2, 3):
            total += 20
        elif e in (4, 5):
            total += 30
        if total < 0:
            total = 0
        if total > 1000:
            total = 1000
        return total
