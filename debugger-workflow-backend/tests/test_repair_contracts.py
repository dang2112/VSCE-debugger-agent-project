import difflib
import os
import unittest
from unittest.mock import patch
from orchestrator.state import (EvidenceItem, EvidenceType, DebugProblem, FailureType,
    RootCauseAnalysisResult, GeneratedPatch, RepairContext, RootCauseHypothesis, SourceFile)
from tools.patches import source_hash, apply_diff


class RepairContractTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch('google.genai.Client'):
            from agents.rca import analyze_root_cause
            from agents.patch_generator import generate_patch
        self.analyze = analyze_root_cause
        self.generate = generate_patch
        self.evidence = EvidenceItem(type=EvidenceType.SOURCE_CODE, source='editor', path='calc.py', content='return a // b')

    def test_fabricated_or_uninspected_evidence_is_rejected(self):
        for supporting, inspected in ((['invented'], ['invented']), ([self.evidence.id], [])):
            result = RootCauseAnalysisResult.model_validate({'hypothesis': {'summary': 'Floor division',
                'root_cause_file': 'calc.py', 'supporting_evidence_ids': supporting}, 'inspected_evidence_ids': inspected})
            with patch('agents.rca.generate_structured', return_value=result), self.assertRaises(ValueError):
                self.analyze(DebugProblem(failure_type=FailureType.TEST_FAILURE), [self.evidence], None, 'analysis')

    def test_model_hashes_are_replaced_with_snapshot_hashes(self):
        original = 'value = 1\n'
        diff = '--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-value = 1\n+value = 2\n'
        context = RepairContext(hypothesis=RootCauseHypothesis(summary='Wrong value'),
            relevant_files=[SourceFile(path='calc.py', content=original)], source_hashes={'calc.py': source_hash(original)},
            editable_paths=['calc.py'])
        with patch('agents.patch_generator.generate_structured', return_value=GeneratedPatch(diff=diff, base_hashes={'other.py': 'spoof'})):
            candidate = self.generate(context, [])
        self.assertEqual(candidate.base_hashes, {'calc.py': source_hash(original)})

    def test_multiple_hunks_apply_at_exact_offsets(self):
        original = ''.join(f'value_{i} = {i}\n' for i in range(12))
        fixed = original.replace('value_1 = 1', 'value_1 = 10').replace('value_10 = 10', 'value_10 = 100')
        diff = ''.join(difflib.unified_diff(original.splitlines(True), fixed.splitlines(True),
                    fromfile='a/calc.py', tofile='b/calc.py', n=1))
        self.assertEqual(apply_diff(diff, {'calc.py': original})['calc.py'], fixed)


    def test_large_source_repair_uses_full_snapshot_with_bounded_total(self):
        from agents.repair_context import build_repair_context
        from orchestrator.state import DebugContext
        content = '# padding\n' * 12300
        diagnosis = RootCauseAnalysisResult(hypothesis=RootCauseHypothesis(summary='Wrong value',
            root_cause_file='calc.py', supporting_evidence_ids=[self.evidence.id]),
            inspected_evidence_ids=[self.evidence.id])
        context = DebugContext(files=[SourceFile(path='calc.py', content=content)])
        repair = build_repair_context(DebugProblem(failure_type=FailureType.TEST_FAILURE),
            diagnosis, [self.evidence], context)
        self.assertEqual(repair.relevant_files[0].content, content)
        self.assertEqual(repair.source_hashes['calc.py'], source_hash(content))
        context.files[0].content = 'x' * 200001
        with self.assertRaisesRegex(ValueError, 'repair context limit'):
            build_repair_context(DebugProblem(failure_type=FailureType.TEST_FAILURE),
                diagnosis, [self.evidence], context)
