# SBFL adapter and agent mode

`tools/sbfl.py` calls the cloned engine at `tools/sbfl/src/sbfl` without importing
it into the API process or modifying the partner repository. It runs pytest with
the engine plugin, then invokes the engine's Ochiai ranker on the resulting JSON.
This is **function-level** localization, not line-level Ochiai.

## Setup

Keep the partner clone at `tools/sbfl`. Install backend requirements, which now
include pytest. The target project must also have its dependencies installed.
By default SBFL uses the backend's Python executable. To use an existing target
virtual environment, set `SBFL_PYTHON_EXECUTABLE` to its Python executable before
starting the backend. This is server configuration, never a model argument.

The SBFL clone is currently an untracked nested repository. Its checkout must be
provisioned separately on another machine; this adapter does not download it.
Pin or manage that dependency separately before deploying.

## Session request

Use the existing session API with `mode: "agent"` and a backend-accessible
`context.workspace_path`. For the partner demo, point it at the absolute path of
`tools/sbfl` and ask to localize the failing demo tests under `tests/demo`, tracing
`src/shopping`. Example (replace the path for your checkout):

```json
{
  "mode": "agent",
  "problem": {
    "failure_type": "test_failure",
    "user_message": "Investigate the failing loyalty discount boundary tests."
  },
  "preparation": {
    "sbfl": {"source_root": "src/shopping", "test_ids": ["tests/demo"]}
  },
  "context": {
    "workspace_path": "E:/debugger-workflow-backend/debugger-workflow-backend/tools/sbfl"
  }
}
```

POST `/debug/sessions`, then POST `/debug/sessions/{id}/run`.
Direct and two-thinking-times modes keep their existing analysis behavior.

## Tools exposed to Gemini

- `run_sbfl(source_root="src", test_ids=[], top_k=10, timeout_seconds=120,
  test_timeout_seconds=15, exclude_internet=true)`: executes tests and returns
  ranked functions, source locations, eligible/excluded counts, and up to three
  recommended files. Empty selectors run `tests/`. `source_root="."` supports a
  flat project. Select the whole relevant suite, including passing tests, rather
  than only failures, for meaningful Ochiai scores.
- `sbfl_list_tests(offset=0, limit=50)`: lists recorded outcomes in the latest
  successful run for this session.
- `sbfl_trace(test_id, offset=0, limit=10)`: retrieves paginated invocation blocks,
  argument values, local changes, exceptions, and return values from that run.
- `read_file(path)`: queues a file-read action for the extension using the existing
  polling/result contract. The session enters `waiting_for_context`. After the
  result is submitted, POST `/run` to continue.

The model sees native function declarations, requests a tool, and receives a
structured function response. The orchestrator validates and dispatches every
call; Gemini automatic function execution is disabled. The model can investigate
again or return a final explanation and proposed fix. This implements the action
and observation loop used by ReAct-style agents without requiring printed private
reasoning. Agent mode now runs initial SBFL preparation automatically before the
first model turn, queues the top distinct source files through the extension,
and starts analysis only after those reads finish. The model can then request
additional SBFL runs, tests, traces, or file reads.

Model/tool history, tool results, selected localization evidence, pending reads,
and the latest SBFL run ID are checkpointed. A resumed session continues pending
tool calls without repeating results already checkpointed. Original Gemini
content parts, including thought signatures, are preserved. A crash between a
subprocess finishing and its checkpoint may still cause that subprocess to rerun.

## Results and execution limits

Artifacts live under `session_memory/{session_id}/sbfl/{run_id}/`: `evidence.json`,
`ranking.json`, `result.json`, pytest/rank logs, and bytecode cache. The LLM cannot
choose artifact paths, the Python executable, or a workspace other than the
session's. Source/test paths are checked for containment, including symlinks.
Commands use argument lists without a shell; pytest selectors cannot inject
options. Inherited/configured addopts are cleared to avoid accidental parallel
execution or redirected artifacts. Project plugins may still affect execution.

Expected failing tests (pytest exit 1) are evidence, not adapter errors. Collection
errors, missing dependencies, wall-clock timeout, absent artifacts, and invalid
arguments become tool errors the model can inspect. No eligible failures produces
`no_eligible_failures`; failures without recorded application functions produce
`no_covered_functions`. Neither supplies a useful localization.

Each run has a wall-clock timeout; its process tree is terminated on timeout.
The engine's separate per-test deadline is cooperative and only covers Python
test bodies. Agent sessions allow 12 model turns and at most 8 tool calls per turn;
large tool observations are truncated with an explicit marker. Simultaneous /run
calls are rejected within one backend process. Cross-process coordination is not
implemented. The /run request remains synchronous until completion or a file-read
pause. Cancellation is checked during SBFL execution (polling every 250 ms) and
terminates the subprocess tree. In-flight model requests finish before their
results can be discarded on cancellation.

Tests execute the workspace's **disk contents**, not unsaved editor buffers.
Localization is diagnostic evidence, not patch verification. This adapter executes
project tests with the Python process's permissions; the SBFL socket guard is not
a sandbox. Remote-only VS Code workspaces still need a remote execution bridge;
only file reads currently use the extension bridge. Traces may contain sensitive
runtime values and persist locally and in model context.

## Validation

Run `python -m unittest discover -s tests -v`. The adapter integration tests execute
a temporary copy of the partner demo, verify its two expected failures and top
ranked discount function, and inspect runtime traces. Agent tests mock the LLM,
not a live Gemini request. No API credits or project network access are needed.


## Automatic preparation configuration

Agent sessions default to this configuration (omit fields to use defaults):

```json
{
  "preparation": {
    "enabled": true,
    "sbfl": {
      "source_root": "src",
      "test_ids": [],
      "top_k": 10,
      "timeout_seconds": 120,
      "test_timeout_seconds": 15,
      "exclude_internet": true
    },
    "max_preload_files": 3,
    "max_file_requests": 20,
    "max_file_chars": 24000,
    "max_source_context_chars": 80000
  }
}
```

Configure the application source root and test suite in the session request;
they are not inferred from a natural-language message. Include passing tests in
the selected suite. An empty `test_ids` means `tests/`; a flat project can use
`source_root: "."`. Setting `enabled: false` retains model-selected tools only.
Direct and two-thinking-times sessions do not run preparation. Older persisted
agent conversations with existing model history continue without preprocessing.

The first `/run` call collects localization and persists a preload plan. Source
files are chosen by ranked positive-score functions, deduplicated in ranking
order, up to `max_preload_files`. Files already supplied by the extension are
reused, including the active editor buffer. Otherwise, poll `/actions`, submit
all results, and call `/run` again. The same extension polling loop handles later
LLM file requests. Retrying `/run` or restarting the backend does not repeat a
checkpointed preparation run or duplicate its reads.

Unavailable tests, collection failures, timeouts, missing backend workspace, no
eligible failures, and absent application coverage do not fabricate rankings.
Preparation records the reason, then requests safe workspace-relative Python
files from the supplied traceback (innermost first) and uses supplied source
context. Out-of-workspace paths are ignored. If no useful source is available,
the agent receives that limitation and can ask for more evidence. A failed preload
is recorded as an error; it does not prevent other files from being analyzed.
Remote-only workspaces still require a future test execution bridge for SBFL.

Initial and retrieved source snapshots are persisted with URI, document version,
dirty status, a SHA-256 of UTF-8 content, and explicit truncation metadata. Ranked
files have raw disk SHA-256 values captured **after collection**, which are
compared to retrieved editor text where available. Different encodings/line
endings can also cause a mismatch. This is provenance, not an isolated immutable
workspace: disk files can change during execution. Unsaved buffers are never
silently written or claimed to have been tested.

Full source snapshots remain in session context. Evidence excerpts and model
source content obey `max_file_chars`; initial source content and later read
observations share `max_source_context_chars` for the conversation. Excerpts
clearly report truncation. The active file takes priority in the initial budget.
File request counts include automatic preloads and later model requests, including
failed reads. Test/trace tools are separately bounded/paginated as above.

`GET /debug/sessions/{id}` additionally returns `preparation_status`,
`pending_actions`, and `agent_turns`. Preparation statuses are `pending`,
`localized` (preload plan checkpointed), `ready`, `fallback`, or `disabled`.
Patch generation, patch application, and verification remain outside this phase.
