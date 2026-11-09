"""Loyalty discount rules used by checkout."""


def loyalty_discount_rate(points: int) -> float:
    """Return the customer's loyalty discount as a fraction."""
    if points < 0:
        raise ValueError("Loyalty points cannot be negative")
    if points > 1000:
        return 0.15
    if points >= 500:
        return 0.10
    return 0.0
