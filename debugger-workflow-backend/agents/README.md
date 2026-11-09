# Agent backend: Anthropic Claude Sonnet

The default provider is now Anthropic, with model claude-sonnet-5-5. All direct
analysis, tool investigation, RCA and patch generation share llm_backend.py.
The orchestrator and frontend remain unchanged.

Add these settings to the backend .env, using a key from the Anthropic Console:

```dotenv
ANTHROPIC_API_KEY=your_anthropic_api_key
DEBUGGER_PROVIDER=anthropic
DEBUGGER_MODEL=claude-sonnet-5-5
```

Restart the Python backend and start a NEW frontend request. Do not paste the key
into chat. A Claude chat subscription is not an Anthropic API credential; the key
must have API access and sufficient credits/quota. No key or billing setting was
created or changed automatically. Until the key is configured, requests fail with
an explicit setup message rather than sending traffic to Gemini.

Optional per-stage overrides:

```dotenv
DEBUGGER_DIRECT_MODEL=claude-sonnet-5-5
DEBUGGER_AGENT_MODEL=claude-sonnet-5-5
DEBUGGER_STRUCTURED_MODEL=claude-sonnet-5-5
```

STRUCTURED covers RCA and patch generation. Use model IDs accessible to your API
account. See Anthropic's current models overview:
https://platform.claude.com/docs/en/models/overview

## Compatibility

The new adapter calls Anthropic's Messages API through httpx (already installed
with google-genai). No package installation or edits outside agents/ are required.
It translates existing Content/function-call objects to assistant tool_use and user
tool_result blocks, preserves call IDs and Claude thinking/signature blocks in
checkpoint metadata, and translates responses back to the orchestrator's existing
internal content format. These internal Python types do not send traffic to Google.

Structured output uses output_config.format with a strict JSON schema. Unsupported
numeric/string/array constraints move to descriptions; the original Pydantic schema
still validates the returned result. Patch base_hashes are assigned by the backend,
so that dynamic dictionary is empty in the generated strict output. Sonnet 5.5
rejects temperature/top_p/top_k, so those Gemini sampling fields are not forwarded.

Calls have a 120-second HTTP timeout. Only transient 500/502/503/504/529 responses
are retried once. Authentication, quota, refusals and truncation are explicit errors.
Credentials are redacted in surfaced provider errors. There is no automatic cross-
provider fallback that might send workspace content to a different service.

## Optional Gemini fallback

Gemini remains an explicit opt-in:

```dotenv
DEBUGGER_PROVIDER=gemini
DEBUGGER_MODEL=gemini-3.1-flash-lite
GEMINI_API_KEY=your_gemini_api_key
```

Clear/update per-stage model overrides when switching providers. Live checks on the
current Gemini key succeeded for 3.1 Flash-Lite (tool call, continuation and JSON).
Other checked endpoints returned zero Pro quota, missing model, or capacity errors.
That fallback is not the default after the requested provider switch.

Claude requests have been verified with mocked HTTP transport, not a live Anthropic
account: no Anthropic key is configured yet. Restart and try checkout-demo once
ANTHROPIC_API_KEY is set.

Validation commands:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s agents/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
