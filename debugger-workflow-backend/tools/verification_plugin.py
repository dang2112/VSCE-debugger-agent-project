"""Record pytest outcomes without importing or modifying application sources."""
import json
import os
from pathlib import Path

_outcomes = {}


def pytest_configure(config):
    _outcomes.clear()


def pytest_runtest_logreport(report):
    if report.failed and report.when != 'call':
        _outcomes[report.nodeid] = 'error'
    elif report.when == 'call' and _outcomes.get(report.nodeid) != 'error':
        _outcomes[report.nodeid] = report.outcome
    elif report.skipped and report.when == 'setup':
        _outcomes.setdefault(report.nodeid, 'skipped')


def pytest_sessionfinish(session, exitstatus):
    Path(os.environ['DEBUGGER_TEST_RESULTS']).write_text(json.dumps({
        'exit_code': int(exitstatus), 'outcomes': _outcomes,
    }), encoding='utf-8')
