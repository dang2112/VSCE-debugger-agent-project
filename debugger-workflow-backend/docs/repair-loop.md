# Repair and isolated verification

Agent investigation can now continue into a structured diagnosis, a reviewable
unified diff, and actual pytest verification. Existing analysis-only requests
remain unchanged. Enable repair explicitly on an agent session:

```json
{
  "mode": "agent",
  "problem": {
    "failure_type": "test_failure",
    "user_message": "Fix fractional division returning a truncated integer",
    "failing_tests": ["tests/test_calc.py::test_fraction"]
  },
  "context": {
    "workspace_path": "E:/projects/example",
    "active_file": {
      "path": "calc.py",
      "content": "def ratio(a, b):\n    return a // b\n",
      "document_version": 4,
      "is_dirty": false
    }
  },
  "preparation": {
    "sbfl": {"source_root": ".", "test_ids": ["tests"]}
  },
  "repair": {
    "enabled": true,
    "max_attempts": 3,
    "test_targets": ["tests"],
    "regression_tests": [],
    "run_full_suite": true,
    "timeout_seconds": 120
  }
}
```

Use the existing create/run/actions/result endpoints. Only `mode: "agent"` accepts
`repair.enabled: true`; direct and two-thinking-times are analysis-only modes.
The frontend must keep servicing pending file reads and call `/run` after results
arrive. `/run` is synchronous until completion or an extension-read pause.

## Pipeline

1. The existing tool agent investigates using SBFL, source snapshots and optional
   document retrieval, then checkpoints its analysis.
2. `agents/rca.py` requests `RootCauseAnalysisResult` as structured model output.
   The backend rejects fabricated evidence IDs, contradictory evidence references,
   missing supporting evidence, and missing source locations.
3. `agents/repair_context.py` builds a deterministic `RepairContext` from cited
   evidence and complete source snapshots. If the root cause file has not been
   loaded, the orchestrator requests it through the extension and resumes later.
4. `tools/verification.py` copies the visible project into a persistent baseline
   snapshot, overlays the supplied editor snapshots in that copy, and reproduces
   the failure **before generating a patch**. A passing, skipped, timed-out or
   broken baseline cannot establish a verified fix.
5. `agents/patch_generator.py` generates a minimal unified diff. The backend
   strictly applies it in memory against known snapshots, rejects test/config
   edits and assigns source hashes itself.
6. Each candidate is applied to a fresh copy of the baseline. The verifier reruns
   reproduced failing node IDs, configured regression selectors, then the configured
   full-suite selectors. It records statuses, command, bounded output, exit code,
   per-test outcomes, and the baseline used.
7. Actual assertion failures feed the next candidate attempt. Invalid generated
   diffs also consume a bounded attempt and provide feedback. Infrastructure errors
   and timeouts stop with `unverified`, rather than repeatedly asking the model to
   change source code to compensate for a broken environment.

Every candidate is generated against the original repair context, not the previous
failed patch. Diagnosis, repair context, snapshot ID, baseline result, candidates,
and verification results are persisted. A backend restart resumes a checkpointed
candidate at verification instead of regenerating it. A crash before a checkpoint
may still repeat a model call or test execution.

## Verification meaning

`GET /debug/sessions/{id}/result` now includes:

- `diagnosis`: structured root cause and supporting evidence IDs;
- `patch`: the last generated valid diff, when present;
- `base_hashes`: SHA-256 of the original UTF-8 text for each touched file;
- `baseline`: reproduction result;
- `verification`: failing/regression/full-suite results, baseline, snapshot ID,
  whether the patch applied in the copy, and any verification error;
- `verification_status`: `passed`, `failed`, or `unverified`.

`completed` means the workflow finished, not necessarily that a fix passed.
`passed` requires an actually reproduced failure and passing configured checks.
An overfitted patch that fixes the original test but fails regression/full-suite
checks is `failed`. Missing dependencies, fixture/collection errors, all-skipped
checks, stale source hashes, and timeouts are `unverified`. Per-stage statuses
separate `failed`, `error`, `timed_out`, and `not_run`. If no failure reproduces,
there is no patch to offer. Exhausting attempts completes with `failed`.

The extension should show the diff and verification scope, compare current document
text to `base_hashes`, and require review before applying. Hash mismatches require
refresh/reanalysis; the backend never applies the candidate to the user workspace.
A failed candidate can still have a diff in the result; do not present it as a
verified fix. A generation error produces no diff for that attempt.

## Execution scope and limits

This phase supports pytest and existing UTF-8 application Python files only.
New/deleted/renamed files, binary patches, dependency changes, test edits, and
configuration edits are rejected. Exact hunk context and line counts are required;
there is no fuzzy patch application. Repair context is bounded to 10 application
files, 100,000 characters per file and 200,000 total source characters.

Snapshots use `.gitignore`-aware visible project discovery. Hidden/generated
files, symlinks, virtual environments and Git metadata are excluded. Missing or
excluded source files, incomplete discovery, and copy-budget overflow stop
verification. Defaults allow up to 3,000 files, 5 MB per file and 50 MB total;
`max_snapshot_files` and `max_snapshot_bytes` can tighten the session limits.
Source/test/configuration snapshot hashes are checked, and a candidate cannot claim
success if its tests alter captured input files. No hardlinks are used.

Tests run in separate copied directories with fixed pytest invocation, selectors
passed after `--`, a fresh bytecode cache, and bounded output. Baseline/candidate
artifacts and manifests live under
`session_memory/{session_id}/verification/{snapshot_id}/`. They persist for review
and restart recovery; automatic retention/deletion is not implemented.

Set `VERIFICATION_PYTHON_EXECUTABLE` before backend startup for the target project's
Python environment. It falls back to `SBFL_PYTHON_EXECUTABLE`, then backend Python.
Install project dependencies into that environment beforehand. The model cannot
choose an interpreter or shell command. Each pytest stage has its own wall-clock
timeout. Cancellation stops active subprocesses and wins over late results.

Editor snapshots are overlaid only in the isolated copy, including unsaved changes;
therefore verification refers to that snapshot, not necessarily current disk or
current editor state. The baseline disk copy is not an atomic filesystem snapshot
of a concurrently edited project. Copy isolation protects normal user edits from
our patch operations; project test code still executes with the backend user's
permissions, so this is not a security sandbox for untrusted tests.

## Validation

Run `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`.
The repair fixture reproduces floor-division failures, rejects a wrong candidate,
passes a second candidate, and checks that original source is unchanged. Tests also
cover restart recovery, missing-source reads, unreproduced failures, invalid diffs,
regression failures, stale hashes, infrastructure errors, timeouts and cancellation.
Gemini investigation and structured generation responses are mocked; pytest,
patch application, snapshotting and feedback/retry orchestration execute for real.
