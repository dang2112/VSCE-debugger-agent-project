from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from sbfl.io import load_json, write_json
from sbfl.ochiai import rank_functions
from sbfl.timeout import positive_seconds


DEFAULT_EVIDENCE = Path(".sbfl/test_evidence.json")
DEFAULT_RANKING = Path(".sbfl/suspiciousness.json")


def _strip_remainder_separator(args: Sequence[str]) -> list[str]:
    args = list(args)
    if args and args[0] == "--":
        return args[1:]
    return args


def collect(source_root: str, output: Path, pytest_args: Sequence[str], exclude_internet: bool = False, test_timeout: float | None = None) -> int:
    pytest_args = _strip_remainder_separator(pytest_args)
    if not pytest_args:
        pytest_args = ["tests/demo", "-q"]

    env = os.environ.copy()
    env["SBFL_TEST_TIMEOUT"] = str(test_timeout) if test_timeout is not None else ""
    env["SBFL_EXCLUDE_INTERNET"] = "1" if exclude_internet else "0"
    env["SBFL_SOURCE_ROOT"] = str(Path(source_root).resolve())
    env["SBFL_OUTPUT"] = str(output.resolve())

    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "sbfl.pytest_plugin",
        *pytest_args,
    ]
    print("[sbfl] collecting evidence:")
    print("       " + " ".join(command))
    completed = subprocess.run(command, env=env, check=False)

    if not output.exists():
        print(f"[sbfl] ERROR: pytest finished but evidence file was not created: {output}")
        return 2

    payload = load_json(output)
    tests = payload.get("tests", [])
    excluded = sum(bool(test.get("excluded_from_ranking")) for test in tests)
    print(f"[sbfl] excluded from ranking: {excluded}")
    passed = sum(test.get("outcome") == "passed" for test in tests)
    failed = sum(test.get("outcome") == "failed" for test in tests)
    setup_failed = sum(test.get("outcome") == "setup_failed" for test in tests)
    print(
        f"[sbfl] evidence written to {output} "
        f"({passed} passed, {failed} failed, {setup_failed} setup failures)"
    )

    # Expected target-program failures should not make evidence collection itself fail.
    return 0


def rank(evidence_path: Path, output: Path) -> int:
    payload = load_json(evidence_path)
    recorded = payload.get("tests", [])
    tests = [test for test in recorded if not test.get("excluded_from_ranking")
             and test.get("outcome") in {"passed", "failed"}]
    failing_count = sum(test.get("outcome") == "failed" for test in tests)
    if failing_count == 0:
        write_json(output, {"schema_version": 1, "total_tests": len(tests),
                            "total_failing": 0, "ranking": [],
                            "status": "no_eligible_failures"})
        print("[sbfl] No failing call-phase tests were recorded; Ochiai cannot localize a fault.")
        return 2

    results = rank_functions(tests)
    ranking_payload = {
        "schema_version": 1,
        "evidence_file": str(evidence_path),
        "total_tests": len(tests),
        "excluded_tests": sum(bool(t.get("excluded_from_ranking")) for t in recorded),
        "total_failing": failing_count,
        "ranking": [item.to_dict() for item in results],
    }
    write_json(output, ranking_payload)

    print("\nFunction-level Ochiai ranking")
    print("=" * 92)
    print(f"{'Rank':>4}  {'Score':>8}  {'FailCov':>7}  {'PassCov':>7}  Function")
    print("-" * 92)
    for item in results:
        print(
            f"{item.rank:>4}  {item.score:>8.4f}  {item.failing_covered:>7}  "
            f"{item.passing_covered:>7}  {item.function_id}"
        )
    print(f"\n[sbfl] ranking written to {output}")
    return 0


def list_tests(evidence_path: Path) -> int:
    payload = load_json(evidence_path)
    for test in payload.get("tests", []):
        print(f"{test.get('outcome', 'unknown'):>12}  {test.get('nodeid')}")
    return 0


def show_trace(evidence_path: Path, nodeid: str) -> int:
    payload = load_json(evidence_path)
    match = next((test for test in payload.get("tests", []) if test.get("nodeid") == nodeid), None)
    if match is None:
        print(f"[sbfl] test not found: {nodeid}")
        return 2

    print(f"Test: {nodeid}")
    print(f"Outcome: {match.get('outcome')}")
    print("Covered functions:")
    for function in match.get("covered_functions", []):
        print(f"  - {function}")
    print("\nInvocation blocks:")
    for block in match.get("invocations", []):
        indent = "  " if block.get("parent_call_id") is not None else ""
        print(
            f"{indent}[{block.get('call_id')}] {block.get('function_name')} "
            f"({block.get('file')}:{block.get('first_line')})"
        )
        if block.get("arguments"):
            print(f"{indent}    args={block.get('arguments')}")
        if block.get("executed_lines"):
            print(f"{indent}    lines={block.get('executed_lines')}")
        if block.get("return_value") is not None:
            print(f"{indent}    return={block.get('return_value')}")
        if block.get("exception"):
            print(f"{indent}    exception={block.get('exception')}")
        changes = block.get("local_changes", [])
        if changes:
            print(f"{indent}    local_changes={json.dumps(changes, ensure_ascii=False)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Function-level SBFL + runtime trace collector")
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect_parser = subparsers.add_parser("collect", help="Run pytest with the SBFL trace plugin")
    collect_parser.add_argument("--exclude-internet", action="store_true")
    collect_parser.add_argument("--test-timeout", type=positive_seconds,
                            help="Skip Python test bodies exceeding SECONDS (cooperative).", metavar="SECONDS")
    collect_parser.add_argument("--source-root", default="src/shopping")
    collect_parser.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE)
    collect_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)

    rank_parser = subparsers.add_parser("rank", help="Compute Ochiai ranking from collected evidence")
    rank_parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    rank_parser.add_argument("--output", type=Path, default=DEFAULT_RANKING)

    run_parser = subparsers.add_parser("run", help="Collect evidence then compute Ochiai ranking")
    run_parser.add_argument("--exclude-internet", action="store_true")
    run_parser.add_argument("--test-timeout", type=positive_seconds,
                            help="Skip Python test bodies exceeding SECONDS (cooperative).", metavar="SECONDS")
    run_parser.add_argument("--source-root", default="src/shopping")
    run_parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    run_parser.add_argument("--output", type=Path, default=DEFAULT_RANKING)
    run_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)

    tests_parser = subparsers.add_parser("tests", help="List recorded pytest node IDs")
    tests_parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)

    trace_parser = subparsers.add_parser("trace", help="Print the trace for one recorded test")
    trace_parser.add_argument("nodeid")
    trace_parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "collect":
        return collect(args.source_root, args.output, args.pytest_args, args.exclude_internet, args.test_timeout)
    if args.command == "rank":
        return rank(args.evidence, args.output)
    if args.command == "run":
        result = collect(args.source_root, args.evidence, args.pytest_args, args.exclude_internet, args.test_timeout)
        if result != 0:
            return result
        return rank(args.evidence, args.output)
    if args.command == "tests":
        return list_tests(args.evidence)
    if args.command == "trace":
        return show_trace(args.evidence, args.nodeid)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
