from __future__ import annotations


def loyalty_discount_rate(points: int) -> float:
    """Return the loyalty discount rate.

    Intended behavior:
    - points < 500: 0%
    - 500 <= points < 1000: 10%
    - points >= 1000: 15%

    There is one intentional boundary bug in this function for the SBFL demo.
    """
    if points < 0:
        raise ValueError("points must be non-negative")

    # INTENTIONAL BUG: this should be `points >= 1000`.
    if points > 1000:
        return 0.15
    if points >= 500:
        return 0.10
    return 0.0


def apply_discount(amount: float, rate: float) -> float:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    if not 0.0 <= rate <= 1.0:
        raise ValueError("rate must be between 0 and 1")
    return round(amount * (1.0 - rate), 2)
