from pricing import checkout_total


def test_checkout_at_1000_points():
    assert checkout_total([40.0, 60.0], loyalty_points=1000) == 85.0
