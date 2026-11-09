# VS Code debugger agent

This repository contains the VS Code extension and its local Python backend.

- `llm-vsce-project-frontend/`: extension UI and backend transport.
- `debugger-workflow-backend/`: orchestration, model calls, SBFL, retrieval and verification.
- `demo-tests/`: standalone sample projects to open in the Extension Development Host; not an application dependency.

## Local development

Requires Python 3.11+ and Node.js/npm. From the repository root in PowerShell:

```powershell
cd debugger-workflow-backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set your development API key in the local `.env`, then start the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

In another terminal, from the repository root:

```powershell
cd llm-vsce-project-frontend
npm install
npm run compile
code .
```

Press F5 in the frontend folder to launch the extension. In the new window, open
`demo-tests/checkout-demo` as the workspace and open `pricing.py`. That project's
README describes its intentional failing test. The backend and extension currently
need access to the same local filesystem. Keep the backend bound to localhost.

You can also open `debugger-agent.code-workspace` to work on both components.
See the frontend README and backend `agents/README.md` for settings and model setup.

## Checks

Run frontend `npm run test:unit` and `npm run lint` from its directory.
Run backend `.\.venv\Scripts\python.exe -m pytest tests agents/tests` from its directory.
The standalone demo intentionally contains a failing test and is not part of those checks.

## Git and collaboration

Use Git from this root. Both components and the standalone demos are ordinary
folders in one repository, with no submodules. Commit related frontend/backend
changes together. Dependencies, local secrets, sessions and generated output are ignored.
Never share your `.env` or copied virtual environments.

The migration commit imports both prior histories as parents. Older commits retain
their original repository-relative paths. Sanitized original branches are preserved
under `refs/archive/backend/` and `refs/archive/frontend/`; their tags are namespaced.
`.env` was removed from imported history. Original Git metadata and bundles are backed
up outside this repository; those private backups may still contain old credentials.
Rotate any credentials previously committed before publishing.

No remote is configured for this combined repository. Create a new private remote
for the project, then set `origin` and push `main`. The old GitHub repositories have
not been changed. Check the contents and partner-code licensing before public distribution.
