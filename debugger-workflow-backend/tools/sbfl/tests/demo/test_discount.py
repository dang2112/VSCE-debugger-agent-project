import pytest

from shopping.discount import loyalty_discount_rate


def test_loyalty_discount_below_threshold():
    assert loyalty_discount_rate(200) == 0.0


def test_loyalty_discount_first_threshold():
    assert loyalty_discount_rate(500) == 0.10


def test_loyalty_discount_above_second_threshold():
    assert loyalty_discount_rate(1500) == 0.15


def test_loyalty_discount_boundary_1000():
    # Intended behavior: 1000 points belongs to the 15% tier.
    assert loyalty_discount_rate(1000) == 0.15
