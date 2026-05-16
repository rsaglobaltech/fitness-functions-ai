"""Cycle 2 anchor."""

from src.reporting.metrics import Metrics


class Dispatcher:
    def dispatch(self, metrics: Metrics) -> None:
        metrics.record("dispatched")


def calculate_rate(
    weight: float,
    dest: str,
    urgent: bool,
    fragile: bool,
    insured: bool,
    signature: bool,
    weekend: bool,
) -> float:
    """Deliberately high cyclomatic complexity (CC ~ 18)."""
    rate = 0.0
    if weight < 1:
        rate = 5
    elif weight < 5:
        rate = 10
    elif weight < 20:
        rate = 25
    else:
        rate = 50

    if dest == "international":
        rate *= 3
    elif dest == "regional":
        rate *= 1.5

    if urgent and weight > 10:
        rate *= 2.5
    elif urgent:
        rate *= 2

    if fragile and not insured:
        rate += 5
    elif fragile and insured:
        rate += 10

    if signature:
        rate += 3

    if weekend and dest == "international":
        rate += 20
    elif weekend and dest == "regional":
        rate += 10
    elif weekend:
        rate += 5

    if rate < 5:
        rate = 5
    if rate > 500:
        rate = 500
    return rate
