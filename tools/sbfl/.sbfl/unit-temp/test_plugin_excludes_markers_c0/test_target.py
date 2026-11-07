
import socket
import pytest

@pytest.fixture(scope="session")
def online():
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError:
        pass
    return 1

def test_shared_one(online): assert online == 1
def test_shared_two(online): assert online == 1

def test_caught():
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError:
        pass

@pytest.mark.requires_internet
def test_marked(): raise AssertionError("must not run")

def test_logic(): assert False
