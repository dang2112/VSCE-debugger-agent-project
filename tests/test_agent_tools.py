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
                         {'run_sbfl', 'sbfl_list_tests', 'sbfl_trace', 'read_file'})

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
