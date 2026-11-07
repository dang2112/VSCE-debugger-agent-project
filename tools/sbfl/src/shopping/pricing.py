from __future__ import annotations

from shopping.discount import apply_discount, loyalty_discount_rate


def subtotal(prices: list[float]) -> float:
    if any(price < 0 for price in prices):
        raise ValueError("prices must be non-negative")
    return round(sum(prices), 2)


def apply_tax(amount: float, tax_rate: float) -> float:
    if not 0.0 <= tax_rate <= 1.0:
        raise ValueError("tax_rate must be between 0 and 1")
    return round(amount * (1.0 + tax_rate), 2)


def calculate_total(
    prices: list[float],
    loyalty_points: int,
    tax_rate: float = 0.0,
) -> float:
    base = subtotal(prices)
    discount_rate = loyalty_discount_rate(loyalty_points)
    discounted = apply_discount(base, discount_rate)
    return apply_tax(discounted, tax_rate)
