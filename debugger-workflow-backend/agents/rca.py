"""Evidence-referenced RCA, validated before entering repair."""
from agents.structured import generate_structured
from orchestrator.state import RootCauseAnalysisResult
from orchestrator.actions import ReadFileArguments


def analyze_root_cause(problem, evidence, fault_localization, analysis: str) -> RootCauseAnalysisResult:
    selected = evidence[-100:]
    result = generate_structured({
        'problem': problem.model_dump(mode='json'), 'investigation': analysis[:24000],
        'evidence': [{**e.model_dump(mode='json'), 'content': e.content[:3000]} for e in selected],
        'localization': fault_localization.model_dump(mode='json') if fault_localization else None,
    }, RootCauseAnalysisResult,
        'Return a structured root cause hypothesis grounded in the supplied evidence IDs. '
        'Identify the application source file to repair using a workspace-relative path. '
        'Include uncertainty and separate intended documented behavior from observed runtime facts. '
        'Cite supporting evidence and list inspected evidence IDs. Do not invent IDs or claim a verified fix.')
    known = {e.id for e in selected}
    used = set(result.inspected_evidence_ids + result.hypothesis.supporting_evidence_ids + result.hypothesis.rejected_evidence_ids)
    if not used.issubset(known) or not result.hypothesis.supporting_evidence_ids:
        raise ValueError('RCA must cite supporting evidence IDs from the supplied evidence')
    if set(result.hypothesis.supporting_evidence_ids) & set(result.hypothesis.rejected_evidence_ids):
        raise ValueError('RCA cannot both support and reject the same evidence')
    if not set(result.hypothesis.supporting_evidence_ids + result.hypothesis.rejected_evidence_ids).issubset(result.inspected_evidence_ids):
        raise ValueError('RCA cited evidence must be listed as inspected')
    if not result.hypothesis.summary.strip() or not result.hypothesis.root_cause_file:
        raise ValueError('RCA has insufficient evidence to identify a repairable source file')
    result.hypothesis.root_cause_file = ReadFileArguments(path=result.hypothesis.root_cause_file).path
    return result
