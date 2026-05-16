"""High-complexity helpers (CC > 15)."""


def compute_total(
    items: list[int],
    coupon: str,
    tier: str,
    weekend: bool,
    holiday: bool,
) -> int:
    total = 0
    for item in items:
        if item > 100:
            total += item * 2
        elif item > 50:
            total += int(item * 1.5)
        else:
            total += item
    if coupon == "SAVE10":
        total = int(total * 0.9)
    elif coupon == "SAVE20":
        total = int(total * 0.8)
    elif coupon == "SAVE30":
        total = int(total * 0.7)
    if tier == "gold":
        total = int(total * 0.95)
    elif tier == "platinum":
        total = int(total * 0.9)
    if weekend and holiday:
        total += 50
    elif weekend:
        total += 25
    elif holiday:
        total += 30
    if total < 0:
        total = 0
    if total > 100000:
        total = 100000
    return total


def categorize(score: int, age: int, active: bool, premium: bool) -> str:
    if score > 90 and age > 18:
        return "A"
    if score > 80 and age > 18:
        return "B"
    if score > 70 and active:
        return "C"
    if score > 60 and premium:
        return "C-"
    if score > 50:
        return "D"
    if score > 40 and active:
        return "E"
    if score > 30 and premium:
        return "E-"
    if score > 20:
        return "F"
    if score > 10 and active:
        return "F-"
    return "Z"
