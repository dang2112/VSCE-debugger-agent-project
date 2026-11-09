import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from google.genai import types
from api.schemas import CreateDebugSessionRequest
from orchestrator.actions import ReadFileResult
from orchestrator.state import SourceFile, DebugStage, EvidenceType
from tools.memorysystem import MemoryStore


def tool(name, args):
    return types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))])


class DocumentAgentTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {'GEMINI_API_KEY': 'test'}), patch('google.genai.Client'):
            from orchestrator.service import DebugOrchestrator
        self.cls = DebugOrchestrator
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'rules.md').write_text('# Payments\nprocess_payment must reject insufficient funds.\n\n## Retry\nOnly retry transient failures.')
        self.store = MemoryStore(self.root / 'session_memory')
        self.service = self.cls(self.store)
        self.sid = self.service.create_session(CreateDebugSessionRequest.model_validate({
            'mode': 'agent', 'preparation': {'enabled': False},
            'problem': {'failure_type': 'runtime_error', 'user_message': 'Explain incorrect payment behavior'},
            'context': {'workspace_path': str(self.root)},
        })).session_id

    def test_real_document_search_restart_and_adaptive_dispatch(self):
        with patch('orchestrator.service.agent_turn', side_effect=[
            tool('document_exact_search', {'query': 'process_payment'}),
            tool('read_file', {'path': 'payment.py'}),
        ]):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
        session = self.store.load(self.sid).session
        search_id = next(iter(session.document_searches))
        self.assertEqual(session.document_searches[search_id]['results'][0]['path'], 'rules.md')
        self.service = self.cls(self.store)
        action = self.service.pending_actions(self.sid)[0]
        self.service.submit_action_result(self.sid, action.action_id, ReadFileResult(file=SourceFile(
            path='payment.py', content='def process_payment(): pass')))
        with patch('orchestrator.service.agent_turn', side_effect=[
            tool('document_adaptive_k', {'search_id': search_id}),
            tool('read_document', {'path': 'rules.md', 'start_line': 1, 'max_lines': 2}),
            types.Content(role='model', parts=[types.Part(text='rules.md:2 requires rejecting insufficient funds.')]),
        ]):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.COMPLETED)
        session = self.store.load(self.sid).session
        self.assertTrue(any(e.type == EvidenceType.LEXICAL_RESULT and e.path == 'rules.md' for e in session.evidence))
        self.assertTrue(any(e.type == EvidenceType.RAG_RESULT for e in session.evidence))
        self.assertTrue(any(e.type == EvidenceType.DOCUMENT for e in session.evidence))
        self.assertEqual([f.path for f in session.context.files], ['payment.py'])

    def test_project_structure_and_missing_semantic_are_tool_observations(self):
        with patch('orchestrator.service.semantic_search', side_effect=RuntimeError('Optional semantic model unavailable')), patch(
            'orchestrator.service.agent_turn', side_effect=[
                tool('project_structure', {'documents_only': True}),
                tool('document_semantic_search', {'query': 'What if funds are low?'}),
                types.Content(role='model', parts=[types.Part(text='Use lexical evidence until semantic model is installed.')]),
            ]
        ):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.COMPLETED)
        session = self.store.load(self.sid).session
        self.assertTrue(any(e.type == EvidenceType.PROJECT_STRUCTURE for e in session.evidence))
        self.assertIn('Optional semantic model unavailable', str(session.agent_history))
        self.assertEqual(session.debug_error, None)
