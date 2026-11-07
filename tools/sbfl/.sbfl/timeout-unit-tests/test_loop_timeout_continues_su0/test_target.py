
from target import endless, logic

def test_slow():
    try:
        endless()
    except Exception:
        raise AssertionError("timeout must bypass application handlers")

def test_logic():
    assert logic() == 2

def test_pass():
    assert logic() == 1
