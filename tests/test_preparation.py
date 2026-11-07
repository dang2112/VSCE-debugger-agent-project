import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from google.genai import types
from api.schemas import CreateDebugSessionRequest
from orchestrator.actions import ActionError, ReadFileResult
from orchestrator.state import DebugStage, SourceFile
from tools.memorysystem import MemoryStore


class PreparationTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), patch("google.genai.Client"):
            from orchestrator.service import DebugOrchestrator
        self.cls = DebugOrchestrator
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / 'workspace'
        self.workspace.mkdir()
        self.store = MemoryStore(self.root / 'memory')
        self.service = self.cls(self.store)

    def create(self, **extra):
        payload = {
            'mode': 'agent', 'problem': {'failure_type': 'test_failure', 'user_message': 'Fix loyalty discount'},
            'context': {'workspace_path': str(self.workspace), 'active_file': {
                'path': 'ui.py', 'content': '# unsaved active file', 'document_version': 4, 'is_dirty': True}},
            'preparation': {'sbfl': {'source_root': 'src/shopping'}},
        }
        payload.update(extra)
        return self.service.create_session(CreateDebugSessionRequest.model_validate(payload)).session_id

    def test_real_preload_restart_and_additional_llm_retrieval(self):
        clone = Path(__file__).resolve().parents[1] / 'tools' / 'sbfl'
        shutil.copytree(clone / 'src' / 'shopping', self.workspace / 'src' / 'shopping')
        shutil.copytree(clone / 'tests' / 'demo', self.workspace / 'tests')
        sid = self.create()
        with patch('orchestrator.service.agent_turn') as model:
            self.assertEqual(self.service.run_session(sid).status, DebugStage.WAITING_FOR_CONTEXT)
            model.assert_not_called()
        pending = self.service.pending_actions(sid)
        self.assertEqual({a.request.arguments.path for a in pending}, {'src/shopping/discount.py', 'src/shopping/pricing.py'})
        self.service = self.cls(self.store)
        for action in pending:
            path = action.request.arguments.path
            self.service.submit_action_result(sid, action.action_id, ReadFileResult(file=SourceFile(
                path=path, content=(self.workspace / path).read_text(), document_version=1)))
        request = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(
            name='read_file', args={'path': 'src/shopping/__init__.py'}))])
        with patch('orchestrator.service.SBFLService.run', side_effect=AssertionError('Must not rerun')),\
             patch('orchestrator.service.agent_turn', return_value=request) as model:
            self.assertEqual(self.service.run_session(sid).status, DebugStage.WAITING_FOR_CONTEXT)
            prompt = model.call_args.args[0][0]['parts'][0]['text']
            self.assertIn('loyalty_discount_rate', prompt)
            self.assertIn('"total_failing": 2', prompt)
            self.assertIn('# unsaved active file', prompt)
        additional = self.service.pending_actions(sid)[0]
        self.service.submit_action_result(sid, additional.action_id, ReadFileResult(file=SourceFile(
            path=additional.request.arguments.path, content='# extra file')))
        with patch('orchestrator.service.agent_turn', return_value=types.Content(
            role='model', parts=[types.Part(text='The boundary condition is wrong.')])):
            self.assertEqual(self.service.run_session(sid).status, DebugStage.COMPLETED)
        session = self.store.load(sid).session
        self.assertEqual(session.preparation_status, 'ready')
        self.assertEqual(session.preparation_summary['total_failing'], 2)
        self.assertEqual(len(list((self.store.directory / sid / 'sbfl').iterdir())), 1)
        self.assertTrue(any(e.path == 'src/shopping/discount.py' and
                            e.metadata.get('document_version') == 1 for e in session.evidence))

    def test_unavailable_fallback_failed_read_and_limits(self):
        sid = self.create(problem={'failure_type': 'runtime_error', 'user_message': 'Fix crash',
                                  'error_log': 'File "src/broken.py", line 1\nFile "../secret.py", line 2'},
                          preparation={'max_file_requests': 1, 'max_file_chars': 1000,
                                       'max_source_context_chars': 1000})
        with patch('orchestrator.service.SBFLService.run', side_effect=TimeoutError('Deadline')),\
             patch('orchestrator.service.agent_turn') as model:
            self.service.run_session(sid)
            model.assert_not_called()
        action = self.service.pending_actions(sid)[0]
        self.assertEqual(action.request.arguments.path, 'src/broken.py')
        self.service.submit_action_result(sid, action.action_id, ActionError(code='not_found', message='Missing'))
        requests = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(
            name='read_file', args={'path': 'src/other.py'}))])
        final = types.Content(role='model', parts=[types.Part(text='Insufficient evidence.')])
        with patch('orchestrator.service.agent_turn', side_effect=[requests, final]) as model:
            self.assertEqual(self.service.run_session(sid).status, DebugStage.COMPLETED)
            self.assertIn('retrieval limit', str(model.call_args.args[0]))
        session = self.store.load(sid).session
        self.assertEqual(session.preparation_status, 'fallback')
        self.assertEqual(session.preparation_summary['preload_results']['src/broken.py']['type'], 'error')

    def test_prompt_budget_does_not_truncate_saved_snapshot(self):
        sid = self.create(context={'active_file': {'path': 'a.py', 'content': 'x' * 5000}},
                          preparation={'enabled': False, 'max_file_chars': 1000, 'max_source_context_chars': 1000})
        with patch('orchestrator.service.agent_turn', return_value=types.Content(
            role='model', parts=[types.Part(text='Answer')])) as model:
            self.service.run_session(sid)
        prompt = model.call_args.args[0][0]['parts'][0]['text']
        self.assertIn('"truncated": true', prompt)
        self.assertNotIn('x' * 1001, prompt)
        session = self.store.load(sid).session
        self.assertEqual(len(session.context.active_file.content), 5000)
        self.assertEqual(len(session.evidence[0].content), 1000)

    def test_no_eligible_failures_continues_with_active_context(self):
        from tools.sbfl import SBFLRunResult
        sid = self.create()
        empty = SBFLRunResult(run_id='a'*32, status='no_eligible_failures', source_root='src',
                              total_tests=2, total_failing=0, excluded_tests=0,
                              pytest_exit_code=0, localization={}, recommended_files=[])
        with patch('orchestrator.service.SBFLService.run', return_value=empty), patch(
            'orchestrator.service.agent_turn', return_value=types.Content(role='model', parts=[types.Part(text='Need a reproducer.')])
        ) as model:
            self.assertEqual(self.service.run_session(sid).status, DebugStage.COMPLETED)
        self.assertEqual(self.store.load(sid).session.preparation_status, 'fallback')
        self.assertIn('no_eligible_failures', str(model.call_args.args[0]))
        self.assertEqual(self.service.pending_actions(sid), [])

    def test_cancellation_during_preparation_does_not_start_model(self):
        sid = self.create()
        def cancel(*args):
            self.service.cancel_session(sid)
            raise RuntimeError('Cancelled')
        with patch('orchestrator.service.SBFLService.run', side_effect=cancel), patch(
            'orchestrator.service.agent_turn'
        ) as model:
            self.assertEqual(self.service.run_session(sid).status, DebugStage.CANCELLED)
            model.assert_not_called()

    def test_read_observations_respect_remaining_context_budget(self):
        sid = self.create(context={'active_file': {'path': 'a.py', 'content': 'x' * 900}},
                          preparation={'enabled': False, 'max_file_chars': 1000, 'max_source_context_chars': 1000})
        read = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(
            name='read_file', args={'path': 'b.py'}))])
        with patch('orchestrator.service.agent_turn', return_value=read):
            self.service.run_session(sid)
        action = self.service.pending_actions(sid)[0]
        self.service.submit_action_result(sid, action.action_id, ReadFileResult(file=SourceFile(
            path='b.py', content='y' * 5000)))
        with patch('orchestrator.service.agent_turn', return_value=types.Content(role='model', parts=[types.Part(text='Done')])) as model:
            self.service.run_session(sid)
        response = model.call_args.args[0][2]['parts'][0]['function_response']['response']
        self.assertEqual(len(response['file']['content']), 100)
        self.assertTrue(response['truncated'])
        self.assertEqual(len(self.store.load(sid).session.context.files[0].content), 5000)
