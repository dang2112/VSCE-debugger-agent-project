# Function-level SBFL + Runtime Trace Demo

This repository is a small, complete vertical slice for the debugging-agent project:

1. a deliberately buggy Python application,
2. a pytest suite with passing and failing tests,
3. a per-test runtime trace + function coverage collector,
4. function-level Ochiai suspiciousness ranking,
5. JSON artifacts that can later be consumed by the RCA Agent.

## Project layout

```text
src/
  shopping/                 # deliberately buggy target application
  sbfl/                     # reusable SBFL + trace module
tests/
  demo/                     # intentionally contains failing tests
  unit/                     # tests for the SBFL engine itself
.sbfl/                      # generated artifacts
```

## Setup

Requires Python 3.10 or newer. Run these commands from the repository root.

### Windows (PowerShell)

```powershell
cd E:\sbfl
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\sbfl.exe --help
```

Replace `E:\sbfl` with your checkout's path. If `.venv` already exists and its
Python works, skip creating it. If `py` is unavailable, use `python` instead.
The editable install installs pytest and creates the `sbfl` command.

These commands do not require activation or a PowerShell execution-policy change.
To use the shorter commands in the rest of this README, optionally activate with:

```powershell
.\.venv\Scripts\Activate.ps1
```

If activation is blocked, keep using the explicit executable paths:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit -q
.\.venv\Scripts\sbfl.exe run --source-root src/shopping -- tests/demo -q
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## 1. Confirm the demo bug

```bash
pytest tests/demo -q
```

Expected result: **6 passed, 2 failed**. The known bug is in
`shopping.discount.loyalty_discount_rate`: `1000` points incorrectly receives 10% instead of 15%.

## 2. Collect per-test coverage + execution traces

```bash
sbfl collect --source-root src/shopping -- tests/demo -q
```

Artifacts are written to:

```text
.sbfl/test_evidence.json
```

Each test stores:

- pass/fail status,
- covered application functions,
- invocation blocks,
- arguments,
- executed lines,
- selected local changes,
- return value / exception.

The demo pytest process exits non-zero because two tests intentionally fail. The `sbfl collect`
command still writes the evidence and returns success if collection itself completed correctly.

## 3. Compute Ochiai suspiciousness

```bash
sbfl rank
```

or run both stages:

```bash
sbfl run --source-root src/shopping -- tests/demo -q
```

The expected top suspicious function is:

```text
shopping/discount.py::loyalty_discount_rate
```

Generated ranking:

```text
.sbfl/suspiciousness.json
```

## 4. Inspect one failing runtime trace

List recorded test node IDs:

```bash
sbfl tests
```

Then:

```bash
sbfl trace "tests/demo/test_discount.py::test_loyalty_discount_boundary_1000"
```

## Ochiai

### Excluding slow test bodies

```bash
sbfl run --exclude-internet --test-timeout 30 --source-root path/to/package -- tests -q
```

`--test-timeout SECONDS` is optional and accepts a finite positive number.
It measures elapsed wall time in each test's call phase, including SBFL tracing
overhead. At the next Python trace event after the deadline, SBFL skips the test
and records `excluded_from_ranking: true` with `exclusion_reason: "test_timeout"`.
It contributes no coverage or counts to ranking; the suite continues. Slow tests
are not added to the internet exclusion cache and are retried on future runs.
A timeout is an exclusion policy, not evidence that a test is irrelevant or buggy.

This is a cooperative Python deadline suitable for long nested loops, not a hard
process timeout. It does not time fixture setup/teardown or test collection, and
cannot interrupt sleep, blocked I/O, or native code until Python execution resumes.
Code that replaces tracing or catches `BaseException` can defeat it. A strict
wall-clock bound on all operations would require process isolation.
For direct pytest use, pass `--sbfl-test-timeout SECONDS` with the SBFL plugin.

### Excluding internet-dependent tests

Enable the Python socket guard when collecting evidence:

```bash
sbfl run --exclude-internet --source-root path/to/package -- tests -q
```

Known internet tests can use `@pytest.mark.requires_internet`; in this mode
they are skipped before setup. Otherwise, external DNS lookups, TCP connections,
and UDP sends are blocked during test setup, execution, and teardown. A detected
attempt raises a pytest skip outcome immediately, bypassing ordinary `OSError`
and `Exception` handlers and their retry loops. The test is excluded from ranking.
Loopback addresses and `localhost` remain allowed. Mocked calls that never reach
sockets remain eligible.

Evidence retains excluded test IDs, reasons, and detected destinations for audit.
Excluded tests contribute no coverage or passing/failing counts to Ochiai.
When fixture setup attempts external access, all tests using that fixture name
are conservatively excluded, including consumers of cached shared fixtures.
This may over-exclude unrelated fixtures with the same name.

Discovered and marked test IDs are saved automatically to `network-exclusions.json`
beside the evidence JSON. With `--exclude-internet`, subsequent runs skip these
tests before fixture setup and tracing. Entries are scoped by pytest project root
and application source root; use consistent roots across runs. Delete the file
or remove an entry to rediscover a test after fixing it. You can override the file
by passing `--sbfl-network-exclusions PATH` after the CLI's `--` separator.
Existing evidence files are not automatically imported into this list.

This is runtime detection, not proof that remaining tests never need internet.
Import-time networking, subprocess/native networking, previously captured socket
functions, and unexecuted branches are not covered. A bare `except:` or an explicit
`except BaseException` can still catch pytest's skip outcome. Shared-fixture teardown
attempts are attributed to the test performing teardown. For these cases, mark
known dependent tests explicitly. This mode does not fix project environment or
dependency incompatibilities.

For function `f`:

```text
Ochiai(f) = nf(f) / sqrt(Nf * (nf(f) + np(f)))
```

where:

- `Nf`: total failing tests,
- `nf(f)`: failing tests that execute `f`,
- `np(f)`: passing tests that execute `f`.

This module performs **function-level** SBFL. The trace collector is separate evidence for the future
RCA Agent; SBFL itself only needs per-test coverage + pass/fail outcomes.

## Reusing this on another project

Install this package into the target environment and point `--source-root` at the application code:

```bash
sbfl run --source-root path/to/your/package -- tests -q
```

Phase-1 assumptions:

- pytest can reproduce the failure,
- the environment is already initialized,
- the target fault is in application code,
- tracing the main pytest thread is sufficient.

The current tracer intentionally avoids advanced concurrency tracing, native frames, and subprocess
instrumentation. Those can be added later without changing the Ochiai engine.
