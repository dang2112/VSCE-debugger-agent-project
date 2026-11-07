from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from sbfl.model import TestEvidence
from sbfl.trace import FunctionTraceRecorder
from sbfl.network import NetworkGuard
from sbfl.timeout import TestDeadline, positive_seconds


_SESSIONS: dict[str, TestEvidence] = {}
_ACTIVE_RECORDERS: dict[str, FunctionTraceRecorder] = {}
_OUTPUT_PATH: Path | None = None
_SOURCE_ROOT: Path | None = None
_GUARD: NetworkGuard | None = None
_NETWORK_FIXTURES: set[str] = set()
_EXCLUSIONS_PATH: Path | None = None
_EXCLUSIONS: dict = {}
_CACHE_KEY = ""
_KNOWN_NETWORK_TESTS: set[str] = set()


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("sbfl")
    group.addoption("--sbfl-test-timeout", type=positive_seconds,
                    default=os.environ.get("SBFL_TEST_TIMEOUT") or None,
                    help="Cooperative Python test-body deadline in seconds.")
    group.addoption("--sbfl-exclude-internet", action="store_true",
                    default=os.environ.get("SBFL_EXCLUDE_INTERNET") == "1")
    group.addoption("--sbfl-network-exclusions", default=None,
                    help="Persistent internet test IDs (default: beside evidence JSON).")
    group.addoption(
        "--sbfl-source-root",
        action="store",
        default=os.environ.get("SBFL_SOURCE_ROOT", "src"),
        help="Only trace Python files under this application source root.",
    )
    group.addoption(
        "--sbfl-output",
        action="store",
        default=os.environ.get("SBFL_OUTPUT", ".sbfl/test_evidence.json"),
        help="Output JSON file for per-test coverage and runtime traces.",
    )


def pytest_configure(config: pytest.Config) -> None:
    global _OUTPUT_PATH, _SOURCE_ROOT, _EXCLUSIONS_PATH, _EXCLUSIONS, _CACHE_KEY
    _SESSIONS.clear()
    _ACTIVE_RECORDERS.clear()
    _NETWORK_FIXTURES.clear()
    _KNOWN_NETWORK_TESTS.clear()
    config.addinivalue_line("markers", "requires_internet: test requires external internet access")
    _SOURCE_ROOT = Path(config.getoption("--sbfl-source-root")).resolve()
    _OUTPUT_PATH = Path(config.getoption("--sbfl-output")).resolve()
    _EXCLUSIONS = {}
    _EXCLUSIONS_PATH = None
    if config.getoption("--sbfl-exclude-internet"):
        configured = config.getoption("--sbfl-network-exclusions")
        _EXCLUSIONS_PATH = Path(configured).resolve() if configured else _OUTPUT_PATH.parent / "network-exclusions.json"
        _CACHE_KEY = f"{config.rootpath.resolve()}|{_SOURCE_ROOT}"
        if _EXCLUSIONS_PATH.exists():
            try:
                _EXCLUSIONS = json.loads(_EXCLUSIONS_PATH.read_text(encoding="utf-8"))
                if not isinstance(_EXCLUSIONS, dict) or any(
                    not isinstance(ids, list) or any(not isinstance(i, str) for i in ids)
                    for ids in _EXCLUSIONS.values()
                ):
                    raise ValueError("expected a mapping of project keys to test ID lists")
            except (ValueError, OSError) as exc:
                raise pytest.UsageError(f"Cannot read {_EXCLUSIONS_PATH}: {exc}") from exc
        _KNOWN_NETWORK_TESTS.update(_EXCLUSIONS.get(_CACHE_KEY, []))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    global _GUARD
    if not item.config.getoption("--sbfl-exclude-internet"):
        yield
        return
    marked = (item.get_closest_marker("requires_internet") is not None
              or item.nodeid in _KNOWN_NETWORK_TESTS
              or bool(_NETWORK_FIXTURES.intersection(item.fixturenames)))
    if marked:
        item.add_marker(pytest.mark.skip(reason="requires internet"))
    with NetworkGuard() as guard:
        _GUARD = guard
        try:
            yield
        finally:
            _GUARD = None
            evidence = _SESSIONS.setdefault(item.nodeid, TestEvidence(nodeid=item.nodeid))
            if marked or guard.attempts:
                _KNOWN_NETWORK_TESTS.add(item.nodeid)
                evidence.excluded_from_ranking = True
                evidence.exclusion_reason = "requires_internet" if marked else "external_network_attempt"
                evidence.network_attempts = guard.attempts


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    guard = _GUARD
    before = len(guard.attempts) if guard else 0
    yield
    if guard and len(guard.attempts) > before:
        # Conservatively exclude all consumers, including cached shared fixtures.
        _NETWORK_FIXTURES.add(fixturedef.argname)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    assert _SOURCE_ROOT is not None
    recorder = FunctionTraceRecorder(item.nodeid, _SOURCE_ROOT)
    _ACTIVE_RECORDERS[item.nodeid] = recorder

    previous_trace = sys.gettrace()
    seconds = item.config.getoption("--sbfl-test-timeout")
    deadline = TestDeadline(float(seconds), recorder) if seconds is not None else None
    sys.settrace(deadline.trace if deadline else recorder.trace)
    try:
        yield
    finally:
        sys.settrace(previous_trace)
        evidence = recorder.finish()
        if deadline and deadline.expired:
            evidence.excluded_from_ranking = True
            evidence.exclusion_reason = "test_timeout"
        _SESSIONS[item.nodeid] = evidence
        _ACTIVE_RECORDERS.pop(item.nodeid, None)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[object]):
    report = (yield).get_result()
    # Use an explicit hook implementation so we can record setup failures too.
    if call.when == "call":
        evidence = _SESSIONS.setdefault(item.nodeid, TestEvidence(nodeid=item.nodeid))
        evidence.outcome = report.outcome
        if call.excinfo is not None:
            evidence.failure = {
                "type": call.excinfo.typename,
                "message": str(call.excinfo.value),
            }
    elif call.when == "setup" and call.excinfo is not None:
        evidence = _SESSIONS.setdefault(item.nodeid, TestEvidence(nodeid=item.nodeid))
        evidence.outcome = "skipped" if report.skipped else "setup_failed"
        evidence.failure = {
            "type": call.excinfo.typename,
            "message": str(call.excinfo.value),
        }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    assert _OUTPUT_PATH is not None
    assert _SOURCE_ROOT is not None
    for item in session.items:
        if _NETWORK_FIXTURES.intersection(item.fixturenames):
            evidence = _SESSIONS.setdefault(item.nodeid, TestEvidence(nodeid=item.nodeid))
            evidence.excluded_from_ranking = True
            evidence.exclusion_reason = "network_dependent_fixture"
            _KNOWN_NETWORK_TESTS.add(item.nodeid)
    if _EXCLUSIONS_PATH is not None:
        _EXCLUSIONS[_CACHE_KEY] = sorted(_KNOWN_NETWORK_TESTS)
        _EXCLUSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = _EXCLUSIONS_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(_EXCLUSIONS, indent=2), encoding="utf-8")
        temporary.replace(_EXCLUSIONS_PATH)
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_line(f"[sbfl] Internet exclusions saved to {_EXCLUSIONS_PATH}")
    _OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "source_root": str(_SOURCE_ROOT),
        "pytest_exitstatus": int(exitstatus),
        "tests": [
            evidence.to_dict()
            for evidence in sorted(_SESSIONS.values(), key=lambda item: item.nodeid)
        ],
    }
    _OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
