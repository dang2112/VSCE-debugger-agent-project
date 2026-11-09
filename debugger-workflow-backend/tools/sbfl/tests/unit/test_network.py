import json
import os
import socket
import subprocess
import sys

import pytest

from sbfl.network import ExternalNetworkBlocked, NetworkGuard, is_local
from sbfl.ochiai import rank_functions


@pytest.mark.parametrize("host", ["localhost", "LOCALHOST.", b"localhost", "127.0.0.1",
                                  "127.42.0.1", "::1", "::ffff:127.0.0.1"])
def test_loopback_classification(host):
    assert is_local(host)


@pytest.mark.parametrize("host", ["localhost.example.com", "localhost..", "192.168.1.1",
                                  "10.0.0.1", "0.0.0.0", "::", "example.com", None])
def test_non_loopback_classification(host):
    assert not is_local(host)


def test_passive_resolution_and_udp_blocking():
    with NetworkGuard() as guard:
        assert socket.getaddrinfo(None, 0, flags=socket.AI_PASSIVE)
        assert not guard.attempts
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            with pytest.raises(ExternalNetworkBlocked):
                sock.sendto(b"never sent", ("192.0.2.1", 443))
        assert guard.attempts == [{"operation": "sendto", "host": "192.0.2.1"}]


def test_preconnected_socket_write_is_blocked():
    # A fake peer lets us exercise this without making an external connection.
    class ConnectedSocket(socket.socket):
        def getpeername(self):
            return ("192.0.2.1", 443)

    original = socket.socket.sendall
    with ConnectedSocket() as sock:
        with pytest.raises(ExternalNetworkBlocked):
            with NetworkGuard():
                sock.sendall(b"never sent")
    assert socket.socket.sendall is original


def test_guard_blocks_without_contacting_network_and_restores():
    original = socket.getaddrinfo
    with NetworkGuard() as guard:
        with pytest.raises(ExternalNetworkBlocked):
            socket.getaddrinfo("example.com", 443)
        with socket.socket() as sock:
            with pytest.raises(ExternalNetworkBlocked):
                sock.connect(("192.0.2.1", 443))
        assert socket.getaddrinfo("127.0.0.1", 80)
        assert len(guard.attempts) == 2
    assert socket.getaddrinfo is original


def test_exclusion_removes_coverage_and_denominator():
    result = rank_functions([
        {"outcome": "failed", "covered_functions": ["logic"]},
        {"outcome": "failed", "covered_functions": ["network"],
         "excluded_from_ranking": True},
        {"outcome": "passed", "covered_functions": ["logic"],
         "excluded_from_ranking": True},
    ])
    assert len(result) == 1
    assert result[0].score == 1
    assert result[0].total_failing == 1


def test_plugin_excludes_markers_caught_attempts_and_shared_fixtures(tmp_path):
    (tmp_path / "test_target.py").write_text('''
import socket
import pytest

@pytest.fixture(scope="session")
def online():
    try:
        socket.getaddrinfo("example.com", 443)
    except OSError:
        pass
    pytest.fail("network guard must abort fixture setup")
    return 1

def test_shared_one(online): assert online == 1
def test_shared_two(online): assert online == 1

def test_caught():
    try:
        socket.getaddrinfo("example.com", 443)
    except Exception:
        pytest.fail("application exception handlers must not catch network skip")
    pytest.fail("network guard must abort the test")

@pytest.mark.requires_internet
def test_marked(): raise AssertionError("must not run")

def test_logic(): assert False
''')
    output = tmp_path / "evidence.json"
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    command = [
        sys.executable, "-m", "pytest", "-p", "sbfl.pytest_plugin",
        "--sbfl-exclude-internet", "--sbfl-source-root", str(tmp_path),
        "--sbfl-output", str(output), "--rootdir", str(tmp_path),
        "--confcutdir", str(tmp_path), "-p", "no:cacheprovider", "-q", "test_target.py",
    ]
    completed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    records = json.loads(output.read_text())["tests"]
    assert len(records) == 5
    for record in records:
        assert record["excluded_from_ranking"] == ("test_logic" not in record["nodeid"])
        if record["excluded_from_ranking"]:
            assert record["outcome"] == "skipped"
    result = rank_functions(records)
    assert result
    assert all(item.total_failing == 1 for item in result)
    cache = tmp_path / "network-exclusions.json"
    assert len(next(iter(json.loads(cache.read_text()).values()))) == 4
    target = tmp_path / "test_target.py"
    target.write_text(target.read_text().replace(
        'socket.getaddrinfo("example.com", 443)',
        'pytest.fail("cached internet test or fixture must never execute")'))
    repeated = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert repeated.returncode == 1, repeated.stdout + repeated.stderr
    assert "4 skipped" in repeated.stdout
    records = json.loads(output.read_text())["tests"]
    for record in records:
        if record["excluded_from_ranking"]:
            assert record["outcome"] == "skipped"
            assert record["invocations"] == []
            assert record["network_attempts"] == []
