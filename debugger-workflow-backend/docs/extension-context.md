# Extension context exchange

Existing session payloads remain valid. New clients should send `problem.user_message`
and workspace identity plus the active editor snapshot:

```json
{
  "mode": "agent",
  "problem": {
    "failure_type": "runtime_error",
    "user_message": "Fix the crash when the divisor is zero",
    "error_log": "ZeroDivisionError"
  },
  "context": {
    "workspace_id": "extension-assigned-workspace-id",
    "workspace_uri": "file:///project",
    "active_file": {
      "path": "src/main.py",
      "uri": "file:///project/src/main.py",
      "content": "result = 1 / divisor\n",
      "document_version": 12,
      "is_dirty": true
    }
  }
}
```

POST this to `/debug/sessions`. `workspace_path` and `files` remain supported.
`active_file` is editor content, including unsaved edits; `files` are other snapshots.
`content_hash` is optional opaque snapshot metadata supplied by the extension; the
backend does not compute or verify it. `document_version` is the VS Code document
version. Identity and URIs do not grant the backend filesystem access.

## Backend requests

The orchestrator/tool adapter queues an action through this internal method:

```python
from orchestrator.actions import ReadFileAction, ReadFileArguments, CoverageAction

action = orchestrator.request_action(
    session_id, ReadFileAction(arguments=ReadFileArguments(path="src/helper.py"))
)
# Or: orchestrator.request_action(session_id, CoverageAction())
```

This persists the action and switches the session to `waiting_for_context`.
`POST /debug/sessions/{session_id}/run` does no work while actions are pending.
There is intentionally no public endpoint for enqueueing backend actions.

## Extension polling and results

1. Poll `GET /debug/sessions/{session_id}/actions`. The response is a JSON array
   of pending actions. Each has `action_id`, `session_id`, `status`, and `request`.
   Polling does not consume an action; deduplicate in-flight work by action ID.
2. Execute the typed request in the corresponding workspace.
3. POST to `/debug/sessions/{session_id}/actions/{action_id}/result`:

```json
{
  "result": {
    "type": "read_file",
    "file": {
      "path": "src/helper.py",
      "uri": "file:///project/src/helper.py",
      "content": "def helper(): pass\n",
      "document_version": 3,
      "is_dirty": false
    }
  }
}
```

A coverage request has `type: "run_tests_with_coverage"` and arguments `runner`
(currently `pytest`), `test_ids` (empty means the suite), and `timeout_seconds`.
These are structured arguments, not a shell command. Its result looks like:

```json
{
  "result": {
    "type": "run_tests_with_coverage",
    "source_snapshot_id": "extension-snapshot-123",
    "tests": [
      {"test_id": "tests/test_main.py::test_zero", "outcome": "failed",
       "covered_lines": {"src/main.py": [1, 2]}}
    ],
    "output": "1 failed"
  }
}
```

Coverage must be per test. The extension must identify the actual source snapshot
used by the test run; a dirty editor buffer is not automatically tested. Coverage
collection and Ochiai ranking are not implemented by this transport.

Report unavailable files, timeouts, or execution failures as:

```json
{"result": {"type": "error", "code": "not_found", "message": "File does not exist"}}
```

A successful submission returns the completed action. Identical retries are
idempotent. Unknown sessions/actions return 404; mismatched result types, paths,
conflicting retries, and cancelled actions return 409. Invalid bodies return 422.
Errors complete the action too, so the agent can choose how to recover.

After all actions return, the prior stage is restored. Call the existing `/run`
endpoint to continue the same session; submitting a result never starts an LLM
call inside the result HTTP request. Read results update source context; all
results are recorded as typed tool-result memory entries. Cancellation invalidates
pending actions. Actions and resume state survive process restarts.

## Scope and extension responsibilities

The extension must enforce workspace containment after URI resolution, including
symlinks, workspace trust, and any execution consent. Backend read requests reject
absolute paths and parent traversal, but cannot enforce remote filesystem access.
Treat test IDs as runner arguments, never interpolate them into a shell command.

Agent mode now selects tools through the LLM, including the local SBFL adapter;
see [sbfl-agent.md](sbfl-agent.md). Background scheduling and cross-process session
locking remain unimplemented. Use a single backend
process; the existing memory store is not designed for concurrent writers.

Agent mode now automatically localizes and preloads files before analysis. See
[sbfl-agent.md](sbfl-agent.md) for preparation configuration, fallback behavior,
and the shared source context limits.
