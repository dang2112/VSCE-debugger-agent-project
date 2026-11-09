"""Generate a strict unified diff and bind it to backend-owned source hashes."""
from agents.structured import generate_structured
from orchestrator.state import GeneratedPatch
from tools.patches import apply_diff


def generate_patch(repair_context, previous_attempts) -> GeneratedPatch:
    patch = generate_structured({
        'repair_context': repair_context.model_dump(mode='json'),
        'previous_attempts': [a.model_dump(mode='json') for a in previous_attempts],
    }, GeneratedPatch,
        'Generate a minimal unified diff for the diagnosed bug. Use --- a/path and +++ b/path '
        'headers and valid @@ hunk line counts. Modify only editable_paths against exactly the supplied '
        'source snapshots. Do not create/delete/rename files or change tests/configuration. '
        'Use prior verification failures to correct the next candidate. Each attempt applies to the '
        'original supplied snapshots, not a prior attempted patch. No Markdown fences. '
        'base_hashes are assigned by the backend; do not infer execution success.')
    sources = {f.path: f.content for f in repair_context.relevant_files}
    changes = apply_diff(patch.diff, sources)
    patch.base_hashes = {path: repair_context.source_hashes[path] for path in changes}
    return patch
