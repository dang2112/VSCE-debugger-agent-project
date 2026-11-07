
import socket
import pytest

@pytest.fixture(scope="session")
def online():
    try:
        pytest.fail("cached internet test or fixture must never execute")
    except OSError:
        pass
    pytest.fail("network guard must abort fixture setup")
    return 1

def test_shared_one(online): assert online == 1
def test_shared_two(online): assert online == 1

def test_caught():
    try:
        pytest.fail("cached internet test or fixture must never execute")
    except Exception:
        pytest.fail("application exception handlers must not catch network skip")
    pytest.fail("network guard must abort the test")

@pytest.mark.requires_internet
def test_marked(): raise AssertionError("must not run")

def test_logic(): assert False
