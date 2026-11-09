import argparse
import json
import os
import subprocess
import sys

import pytest

from sbfl.cli import build_parser, rank
from sbfl.timeout import positive_seconds


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "invalid"])
def test_invalid_timeout(value):
    with pytest.raises(argparse.ArgumentTypeError):
        positive_seconds(value)


def test_timeout_cli_option():
    args = build_parser().parse_args(["run", "--test-timeout", "30", "--", "tests"])
    assert args.test_timeout == 30


def test_loop_timeout_continues_suite_and_excludes_from_ranking(tmp_path):
    (tmp_path / "target.py").write_text('''
def endless():
    while True:
        for i in range(1000):
            value = i * i

def logic():
    return 1
''')
    (tmp_path / "test_target.py").write_text('''
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
''')
    evidence = tmp_path / "evidence.json"
    env = os.environ.copy()
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["SBFL_TEST_TIMEOUT"] = ""
    env["SBFL_EXCLUDE_INTERNET"] = "0"
    result = subprocess.run([
        sys.executable, "-m", "pytest", "-p", "sbfl.pytest_plugin",
        "--sbfl-test-timeout", "0.5", "--sbfl-source-root", str(tmp_path),
        "--sbfl-output", str(evidence), "--rootdir", str(tmp_path),
        "--confcutdir", str(tmp_path), "-p", "no:cacheprovider", "test_target.py", "-q",
    ], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stdout + result.stderr
    records = json.loads(evidence.read_text())["tests"]
    slow = next(t for t in records if t["nodeid"].endswith("::test_slow"))
    assert slow["outcome"] == "skipped"
    assert slow["excluded_from_ranking"]
    assert slow["exclusion_reason"] == "test_timeout"
    assert sorted(t["outcome"] for t in records) == ["failed", "passed", "skipped"]
    assert not (tmp_path / "network-exclusions.json").exists()
    output = tmp_path / "ranking.json"
    assert rank(evidence, output) == 0
    ranked = json.loads(output.read_text())
    assert ranked["total_tests"] == 2
    assert ranked["total_failing"] == 1
    assert all("endless" not in r["function_id"] for r in ranked["ranking"])
