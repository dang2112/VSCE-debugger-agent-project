"""Shopping-cart totals."""
from discounts import loyalty_discount_rate


def subtotal(prices: list[float]) -> float:
    """Add item prices, rounded to cents."""
    if any(price < 0 for price in prices):
        raise ValueError("Item prices cannot be negative")
    return round(sum(prices), 2)


def checkout_total(prices: list[float], loyalty_points: int) -> float:
    """Apply the customer's loyalty discount to the cart subtotal."""
    return round(subtotal(prices) * (1 - loyalty_discount_rate(loyalty_points)), 2)
