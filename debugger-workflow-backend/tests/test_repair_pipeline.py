import difflib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from google.genai import types
from api.schemas import CreateDebugSessionRequest
from orchestrator.state import DebugStage, VerificationStatus, TestStageStatus
from tools.memorysystem import MemoryStore

ORIGINAL = 'def ratio(a, b):\n    return a // b\n'
FIXED = ORIGINAL.replace('//', '/')


def diff_for(content):
    return ''.join(difflib.unified_diff(ORIGINAL.splitlines(True), content.splitlines(True),
                                      fromfile='a/calc.py', tofile='b/calc.py'))


class RepairPipelineTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch('google.genai.Client'):
            from orchestrator.service import DebugOrchestrator
        self.cls = DebugOrchestrator
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'project'
        (self.workspace / 'tests').mkdir(parents=True)
        (self.workspace / 'calc.py').write_text(ORIGINAL)
        (self.workspace / 'tests' / 'test_calc.py').write_text(
            'from calc import ratio\n\ndef test_fraction():\n    assert ratio(3, 2) == 1.5\n\ndef test_exact():\n    assert ratio(4, 2) == 2\n')
        self.store = MemoryStore(self.root / 'session_memory')
        self.service = self.cls(self.store)
        self.sid = self.service.create_session(CreateDebugSessionRequest.model_validate({
            'mode': 'agent', 'preparation': {'enabled': False},
            'repair': {'enabled': True, 'max_attempts': 2, 'regression_tests': ['tests/test_calc.py::test_exact']},
            'problem': {'failure_type': 'test_failure', 'user_message': 'Fix fractional division',
                        'failing_tests': ['tests/test_calc.py::test_fraction']},
            'context': {'workspace_path': str(self.workspace), 'files': [{'path': 'calc.py', 'content': ORIGINAL}]},
        })).session_id
        self.evidence = self.store.load(self.sid).session.evidence[0].id

    def model(self, candidates):
        candidates = iter(candidates)
        self.patch_requests = []
        def generate(**kwargs):
            payload = json.loads(kwargs['contents'])
            if 'repair_context' in payload:
                self.patch_requests.append(payload)
                return SimpleNamespace(text=json.dumps({'diff': diff_for(next(candidates)), 'explanation': 'Use true division.'}))
            return SimpleNamespace(text=json.dumps({
                'hypothesis': {'summary': 'Floor division truncates fractional results.', 'root_cause_file': 'calc.py',
                               'supporting_evidence_ids': [self.evidence], 'confidence': .9},
                'inspected_evidence_ids': [self.evidence],
            }))
        return generate

    def investigation(self):
        return patch('orchestrator.service.agent_turn', return_value=types.Content(role='model', parts=[
            types.Part(text='The implementation uses floor division instead of true division.')]))

    def test_real_reproduction_failed_candidate_retry_and_verified_diff(self):
        from agents.direct_debugger import client
        with self.investigation(), patch.object(client.models, 'generate_content', side_effect=self.model([
            ORIGINAL.replace('a // b', 'a / (b + 1)'), FIXED
        ])):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.COMPLETED)
        result = self.service.get_result(self.sid)
        self.assertEqual(result.verification_status, VerificationStatus.PASSED)
        self.assertEqual(result.verification.failing_tests.status, TestStageStatus.PASSED)
        self.assertEqual(result.verification.regression_tests.status, TestStageStatus.PASSED)
        self.assertEqual(result.verification.full_suite.status, TestStageStatus.PASSED)
        self.assertEqual(result.baseline['status'], 'failed')
        self.assertEqual(self.patch_requests[1]['previous_attempts'][0]['verification']['overall_status'], 'failed')
        self.assertIn('calc.py', result.base_hashes)
        self.assertEqual((self.workspace / 'calc.py').read_text(), ORIGINAL)
        session = self.store.load(self.sid).session
        self.assertEqual(len(session.patch_attempts), 2)
        self.assertEqual(len(list((self.store.directory / self.sid / 'verification').iterdir())), 1)
        self.assertIn('-    return a // b', result.patch)

    def test_resume_persisted_candidate_without_regeneration(self):
        from agents.direct_debugger import client
        with self.investigation(), patch.object(client.models, 'generate_content', side_effect=self.model([FIXED])), patch(
            'orchestrator.service.VerificationService.verify', side_effect=RuntimeError('Interrupted before checks')
        ):
            with self.assertRaisesRegex(RuntimeError, 'Interrupted'):
                self.service.run_session(self.sid)
        self.service = self.cls(self.store)
        with patch('orchestrator.service.generate_patch', side_effect=AssertionError('Must not regenerate')),\
             patch('orchestrator.service.analyze_root_cause', side_effect=AssertionError('Must not repeat RCA')):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.COMPLETED)
        self.assertEqual(self.service.get_result(self.sid).verification_status, VerificationStatus.PASSED)
        self.assertEqual(len(self.store.load(self.sid).session.patch_attempts), 1)

    def test_no_reproduced_failure_does_not_generate_a_patch(self):
        from agents.direct_debugger import client
        # The supplied editor snapshot already fixes the on-disk bug; baseline must use it.
        session = self.store.load(self.sid).session
        session.context.files[0].content = FIXED
        self.store.save(session)
        with self.investigation(), patch.object(client.models, 'generate_content', side_effect=self.model([])):
            self.service.run_session(self.sid)
        self.assertEqual(self.patch_requests, [])
        self.assertEqual(self.service.get_result(self.sid).verification_status, VerificationStatus.UNVERIFIED)
        self.assertEqual((self.workspace / 'calc.py').read_text(), ORIGINAL)

    def test_invalid_patch_attempts_are_bounded(self):
        from agents.direct_debugger import client
        with self.investigation(), patch.object(client.models, 'generate_content', side_effect=self.model([ORIGINAL, ORIGINAL])):
            self.service.run_session(self.sid)
        session = self.store.load(self.sid).session
        self.assertEqual(session.final_status, VerificationStatus.FAILED)
        self.assertEqual(len(session.patch_attempts), 2)
        self.assertTrue(all(a.generation_error for a in session.patch_attempts))
        self.assertIsNone(self.service.get_result(self.sid).patch)

    def test_missing_source_snapshot_pauses_and_then_repairs(self):
        from agents.direct_debugger import client
        from orchestrator.actions import ReadFileResult
        from orchestrator.state import SourceFile
        session = self.store.load(self.sid).session
        session.context.files = []
        self.store.save(session)
        with self.investigation(), patch.object(client.models, 'generate_content', side_effect=self.model([])):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
        action = self.service.pending_actions(self.sid)[0]
        self.service = self.cls(self.store)
        self.service.submit_action_result(self.sid, action.action_id, ReadFileResult(file=SourceFile(path='calc.py', content=ORIGINAL)))
        with patch('orchestrator.service.analyze_root_cause', side_effect=AssertionError('RCA already checkpointed')), patch.object(
            client.models, 'generate_content', side_effect=self.model([FIXED])
        ):
            self.service.run_session(self.sid)
        self.assertEqual(self.service.get_result(self.sid).verification_status, VerificationStatus.PASSED)

    def test_cancellation_during_verification_preserves_cancelled_state(self):
        from agents.direct_debugger import client
        def cancel(*args):
            self.service.cancel_session(self.sid)
            raise RuntimeError('Verification cancelled')
        with self.investigation(), patch.object(client.models, 'generate_content', side_effect=self.model([FIXED])), patch(
            'orchestrator.service.VerificationService.verify', side_effect=cancel
        ):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.CANCELLED)
        self.assertEqual(self.store.load(self.sid).session.stage, DebugStage.CANCELLED)
        self.assertEqual((self.workspace / 'calc.py').read_text(), ORIGINAL)
