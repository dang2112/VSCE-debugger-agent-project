from shopping.pricing import calculate_total


def test_total_without_discount():
    assert calculate_total([40.0, 60.0], 0) == 100.0


def test_total_with_ten_percent_discount():
    assert calculate_total([40.0, 60.0], 500) == 90.0


def test_total_with_fifteen_percent_discount():
    assert calculate_total([40.0, 60.0], 1500) == 85.0


def test_total_boundary_1000_points():
    # Intended behavior: 1000 points gets 15%, so 100 -> 85.
    assert calculate_total([40.0, 60.0], 1000) == 85.0
