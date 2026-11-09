import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from google.genai import types
from api.schemas import CreateDebugSessionRequest
from orchestrator.actions import ReadFileResult
from orchestrator.state import DebugStage, SourceFile
from tools.memorysystem import MemoryStore
from tools.sbfl import SBFLRunResult


def calls(*items):
    return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
        name=name, args=args, id=f"call-{index}")) for index, (name, args) in enumerate(items)])


def answer(text="Diagnosis"):
    return types.Content(role="model", parts=[types.Part(text=text)])


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), patch("google.genai.Client"):
            from orchestrator.service import DebugOrchestrator
        self.cls = DebugOrchestrator
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = MemoryStore(self.directory.name)
        self.service = self.cls(self.store)
        self.sid = self.service.create_session(CreateDebugSessionRequest.model_validate({
            "mode": "agent", "preparation": {"enabled": False}, "problem": {"failure_type": "test_failure", "user_message": "Fix it"},
            "context": {"workspace_path": str(Path(self.directory.name).resolve())},
        })).session_id

    def test_sbfl_observation_and_final_answer(self):
        result = SBFLRunResult.model_validate({
            "run_id": "a" * 32, "status": "ranked", "source_root": "src", "total_tests": 3,
            "total_failing": 1, "excluded_tests": 0, "pytest_exit_code": 1,
            "localization": {"candidates": [{"path": "src/main.py", "suspiciousness": 0.7}]},
            "recommended_files": ["src/main.py"],
        })
        with patch("orchestrator.service.SBFLService.run", return_value=result) as sbfl, patch(
            "orchestrator.service.agent_turn", side_effect=[calls(("run_sbfl", {})), answer()]
        ) as model:
            response = self.service.run_session(self.sid)
        self.assertEqual(response.status, DebugStage.COMPLETED)
        self.assertEqual(sbfl.call_count, 1)
        self.assertEqual(model.call_args.args[0][2]['parts'][0]['function_response']['response']['total_failing'], 1)
        session = self.store.load(self.sid).session
        self.assertEqual(session.sbfl_run_id, "a" * 32)
        self.assertEqual(session.fault_localization.candidates[0].path, "src/main.py")
        self.assertEqual(session.final_explanation, "Diagnosis")

    def test_read_pause_restart_multiple_calls_and_signatures(self):
        content = calls(("read_file", {"path": "src/a.py"}), ("read_file", {"path": "src/b.py"}))
        content.parts[0].thought_signature = b"signature"
        with patch("orchestrator.service.agent_turn", return_value=content) as model:
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
            self.assertEqual(model.call_count, 1)
        for path in ("src/a.py", "src/b.py"):
            action = self.service.pending_actions(self.sid)[0]
            self.assertEqual(action.request.arguments.path, path)
            self.service.submit_action_result(self.sid, action.action_id, ReadFileResult(
                file=SourceFile(path=path, content=f"contents for {path}")))
            self.service = self.cls(MemoryStore(self.directory.name))
            if path.endswith('a.py'):
                with patch("orchestrator.service.agent_turn") as model:
                    self.assertEqual(self.service.run_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
                    model.assert_not_called()
        with patch("orchestrator.service.agent_turn", return_value=answer()) as model:
            self.service.run_session(self.sid)
        history = model.call_args.args[0]
        model_content = types.Content.model_validate(history[1])
        self.assertEqual(model_content.parts[0].thought_signature, b"signature")
        tool_content = types.Content.model_validate(history[2])
        self.assertEqual(tool_content.role, "user")
        self.assertEqual(len(tool_content.parts), 2)
        self.assertEqual(tool_content.parts[1].function_response.response['file']['path'], 'src/b.py')

    def test_tool_errors_are_observations_and_budget_is_enforced(self):
        with patch("orchestrator.service.agent_turn", side_effect=[
            calls(("unknown", {}), ("sbfl_trace", {"test_id": "test_x"}), ("read_file", {"path": "../bad"})), answer()
        ]) as model:
            self.service.run_session(self.sid)
            responses = model.call_args.args[0][-2]['parts']
            self.assertTrue(all('error' in p['function_response']['response'] for p in responses))
        session = self.store.load(self.sid).session
        session.stage = DebugStage.CREATED
        session.agent_history = []
        session.agent_turns = 0
        session.max_agent_turns = 1
        self.store.save(session)
        with patch("orchestrator.service.agent_turn", return_value=calls(("unknown", {}))):
            with self.assertRaisesRegex(RuntimeError, 'turn limit'):
                self.service.run_session(self.sid)
        self.assertEqual(self.store.load(self.sid).session.stage, DebugStage.FAILED)

    def test_native_declarations_and_manual_dispatch(self):
        from agents.tool_agent import agent_turn
        from agents.direct_debugger import client
        response = types.GenerateContentResponse(candidates=[types.Candidate(content=answer())])
        with patch.object(client.models, 'generate_content', return_value=response) as generate:
            self.assertEqual(agent_turn([{'role': 'user', 'parts': [{'text': 'debug'}]}]), answer())
        config = generate.call_args.kwargs['config']
        self.assertTrue(config.automatic_function_calling.disable)
        self.assertEqual({f.name for f in config.tools[0].function_declarations},
                         {'run_sbfl', 'sbfl_list_tests', 'sbfl_trace', 'read_file', 'project_structure',
                          'document_exact_search', 'document_lexical_search', 'document_semantic_search',
                          'document_adaptive_k', 'read_document'})

    def test_cancel_during_tool_does_not_complete_session(self):
        def cancel(*args):
            self.service.cancel_session(self.sid)
            raise RuntimeError("Cancelled during collection")
        with patch("orchestrator.service.agent_turn", return_value=calls(("run_sbfl", {}))), patch(
            "orchestrator.service.SBFLService.run", side_effect=cancel
        ):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.CANCELLED)
        self.assertEqual(self.store.load(self.sid).session.stage, DebugStage.CANCELLED)

    def test_concurrent_run_rejected(self):
        def nested(history):
            with self.assertRaisesRegex(ValueError, "already running"):
                self.service.run_session(self.sid)
            return answer()
        with patch("orchestrator.service.agent_turn", side_effect=nested):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.COMPLETED)

    def test_gemini_function_responses_use_user_role_including_old_checkpoints(self):
        from agents.tool_agent import agent_turn
        from agents.direct_debugger import client
        content = calls(("read_file", {"path": "src/a.py"}))
        content.parts[0].thought_signature = b"signature"
        history = [
            {"role": "user", "parts": [{"text": "debug"}]},
            content.model_dump(mode="json", exclude_none=True),
            {"role": "tool", "parts": [{"function_response": {
                "id": "call-0", "name": "read_file", "response": {"content": "source"}
            }}]},
        ]
        response = types.GenerateContentResponse(candidates=[types.Candidate(content=answer())])
        with patch.object(client.models, "generate_content", return_value=response) as generate:
            agent_turn(history)
        sent = generate.call_args.kwargs["contents"]
        self.assertEqual([item.role for item in sent], ["user", "model", "user"])
        self.assertEqual(sent[1].parts[0].thought_signature, b"signature")
        self.assertEqual(sent[2].parts[0].function_response.id, "call-0")
        self.assertEqual(sent[2].parts[0].function_response.response, {"content": "source"})
        self.assertEqual(history[2]["role"], "tool")  # Existing memory remains readable.


    def test_late_source_range_survives_action_pause_and_restart(self):
        source = 'prefix = 0\n' * 3000 + 'def target():\n    return 42\n'
        with patch('orchestrator.service.agent_turn', return_value=calls(('read_file', {
            'path': 'large.py', 'start_line': 3001, 'end_line': 3002}))):
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
        action = self.service.pending_actions(self.sid)[0]
        self.service.submit_action_result(self.sid, action.action_id,
            ReadFileResult(file=SourceFile(path='large.py', content=source, document_version=7)))
        self.service = self.cls(MemoryStore(self.directory.name))
        with patch('orchestrator.service.agent_turn', return_value=answer()) as model:
            self.service.run_session(self.sid)
        result = model.call_args.args[0][-2]['parts'][0]['function_response']['response']
        self.assertEqual(result['file']['content'], 'def target():\n    return 42\n')
        self.assertEqual(result['start_line'], 3001)
        self.assertEqual(result['file']['document_version'], 7)
        session = self.store.load(self.sid).session
        self.assertEqual(session.context.files[0].content, source)
        self.assertTrue(any(e.source == 'agent.read_file' and 'def target' in e.content for e in session.evidence))

    def test_source_search_locates_symbols_after_initial_prefix(self):
        from agents.context_preparation import source_excerpt
        from orchestrator.actions import ReadFileArguments
        source = 'padding = 0\n' * 3000 + 'def _parse_mpd_formats():\n    return []\n'
        content, metadata = source_excerpt(source, ReadFileArguments(path='large.py', search='_parse_mpd_formats'), 24000)
        self.assertIn('def _parse_mpd_formats', content)
        self.assertEqual(metadata['matching_lines'], [3001])
        self.assertGreater(metadata['start_line'], 1)
        with self.assertRaisesRegex(ValueError, 'budget exhausted'):
            source_excerpt(source, ReadFileArguments(path='large.py'), 0)
