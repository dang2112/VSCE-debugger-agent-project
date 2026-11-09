from pricing import subtotal


def test_subtotal_adds_prices():
    assert subtotal([40.0, 60.0]) == 100.0
