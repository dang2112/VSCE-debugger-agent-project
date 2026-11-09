# Python Debug Agent extension

This VS Code extension connects to the sibling Python backend. It captures the
selected editor (including unsaved edits), creates a debug session, displays
progress, answers workspace-file requests, and displays explanations and patch
verification results. Each Debug starts an independent backend session; the visible
transcript shows the current run.

## Start development

1. Start the backend in a terminal from its own directory:

   ```powershell
   cd ..\debugger-workflow-backend
   .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
   ```

   Install its requirements and configure its model credentials first (see `../debugger-workflow-backend/agents/README.md`). If the
   virtual environment was moved, recreate it and install `requirements.txt`.
2. Open **this frontend folder** in VS Code. Run `npm install` if dependencies are
   missing, then `npm run compile`.
3. Press F5 (`Run Extension`) to launch an Extension Development Host.
4. In that new window, open the project you want to debug. For manual experimentation,
   open the existing `demo-tests` folder; it remains a normal external user project
   and is not imported by the extension or backend.
5. Open `main.py`, select the **Python Debug Agent** activity-bar icon, type a
   question, optionally paste the traceback, then Debug. `Change` can
   select a file within the open project.

For `demo-tests/main.py`, ask why `average([])` crashes and paste its traceback.
No pytest tests are required for diagnosis. Without reproducible tests, SBFL falls
back to supplied context and repair remains unverified. The extension does not
run the selected Python script automatically or invent its expected behavior.

## Modes and settings

Settings use the `pythonDebugAgent` prefix:

- `backendUrl`: default `http://127.0.0.1:8000`.
- `mode`: `agent` (default), `direct`, or `two-thinking-times`.
- `repairEnabled`: default unchecked. Also controllable per request in the panel.
- `sbflEnabled`: initial automatic localization in agent mode; default true.
- `sourceRoot`: workspace-relative application source root; default `.`. Use `src`
  or a package directory when applicable.
- `testTargets`: pytest suite selectors; default `["tests"]`. Includes passing
  and failing tests for localization and full-suite verification.

Use failure details for traceback output and optional failing pytest selectors.
Direct/review modes only analyze supplied editor context. Agent mode can request
more files and run tests on the backend. Repair requires `agent` plus the repair
checkbox and reproducible tests. An ordinary script without tests is useful for
manual diagnosis; adding tests is a separate project decision.

Progress remains visible while the backend's synchronous `/run` call is pending.
Cancel sends `/cancel` independently and stops extension requests. If cancellation
cannot reach the backend, it may still be running; inspect its terminal/session.
Closing the webview or deactivating the extension requests cancellation too.

## Results

`Open patch` opens the returned unified diff for review. `Session details` opens
source hashes, structured diagnosis, baseline and verification details as JSON.
A completed session is not necessarily a verified fix: check `verification_status`.
Patch application is intentionally not performed by this integration. Existing
source and unsaved editor buffers are not modified.

File requests are tied to the workspace containing the initially selected file,
not whichever editor becomes active later. Local containment is checked after
symlink resolution; hidden/dependency/session files and files over 1 MB are rejected.
The extension reports read failures as structured action errors so the session can
continue. Workspace trust is required before running a session.

This version assumes backend and extension workspace share the same local
filesystem. Remote-only workspaces need an execution/document bridge. The backend
is started manually; extension-managed Python startup/packaging is not included.
The current coverage action transport returns an explicit unsupported-action error;
SBFL/test execution currently runs on the backend, not in the extension.

## Validation

```powershell
npm run compile
npm run lint
npm run test:unit
```

Unit tests use Node's built-in runner with a local HTTP test server to exercise the
session/action protocol, progress polling, cancellation and errors, plus real
filesystem containment checks. They do not call Gemini or require VS Code GUI.
`npm test` remains the optional VS Code Extension Host test runner.


## Chat composer and session reset

The panel uses a chat transcript with one joined three-section composer: request,
error output, and failing tests. Debug (or Ctrl/Cmd+Enter) captures the current
Python editor and displays the inputs together as ONE user message. The API still
receives separate structured fields for correct failure analysis.

The composer clears after the extension captures a valid source snapshot. Each new
Debug replaces the previous run's transcript. New session explicitly clears the
chat, all three draft inputs, status, and old patch/details controls. Completed
results remain visible until a reset or the next Debug; backend checkpoint files
are not deleted. Cancel an active run before resetting. Debug options are retained.

Agent sessions automatically load a bounded metadata-only project overview before
SBFL/analysis, even if SBFL preparation is disabled. Source contents are loaded
separately from the active editor and requested relevant files.
