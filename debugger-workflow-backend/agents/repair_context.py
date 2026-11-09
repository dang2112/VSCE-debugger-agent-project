"""Deterministic repair context using full source snapshots and cited evidence."""
from orchestrator.state import RepairContext
from tools.patches import editable_path, source_hash


def build_repair_context(problem, diagnosis, evidence, context) -> RepairContext:
    files = {f.path: f for f in context.files}
    if context.active_file:
        files[context.active_file.path] = context.active_file
    root = editable_path(diagnosis.hypothesis.root_cause_file)
    if root not in files:
        raise ValueError('Root cause source snapshot must be retrieved before repair')
    ordered = [files[root]] + [f for p, f in files.items() if p != root]
    relevant = []
    for file in ordered:
        try:
            editable_path(file.path)
        except ValueError:
            continue
        if len(file.content) > 100000:
            raise ValueError('Source snapshot exceeds the repair context limit: ' + file.path)
        relevant.append(file)
        if len(relevant) == 10:
            break
    if sum(len(f.content) for f in relevant) > 200000:
        raise ValueError('Repair context exceeds the source character budget')
    cited = set(diagnosis.hypothesis.supporting_evidence_ids)
    selected = [e.model_copy(update={'content': e.content[:3000]}) for e in evidence if e.id in cited]
    if not selected or not cited.issubset({e.id for e in selected}):
        raise ValueError('Repair context is missing cited supporting evidence')
    return RepairContext(hypothesis=diagnosis.hypothesis, problem=problem,
        selected_evidence=selected, relevant_files=relevant, editable_paths=[f.path for f in relevant],
        source_hashes={f.path: source_hash(f.content) for f in relevant},
        notes='Modify existing application Python files only; do not modify tests, configuration, dependencies or documents.')
