import os
import tempfile
import unittest
from unittest.mock import patch

from api.schemas import CreateDebugSessionRequest
from orchestrator.actions import ReadFileAction, ReadFileArguments, ReadFileResult, ActionError, CoverageAction, CoverageResult
from orchestrator.state import DebugStage, SourceFile
from tools.memorysystem import MemoryStore


class WorkspaceActionTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), patch("google.genai.Client"):
            from orchestrator.service import DebugOrchestrator
        self.cls = DebugOrchestrator
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.service = self.cls(MemoryStore(self.directory.name))
        request = CreateDebugSessionRequest.model_validate({
            "problem": {"failure_type": "runtime_error", "user_message": "Fix division"},
            "context": {"workspace_id": "project", "workspace_uri": "vscode-remote://host/project",
                        "active_file": {"path": "main.py", "uri": "file:///project/main.py",
                                        "content": "unsaved", "document_version": 4, "is_dirty": True}},
        })
        self.sid = self.service.create_session(request).session_id

    def test_round_trip_restart_wait_resume_and_prompt(self):
        action = self.service.request_action(self.sid, ReadFileAction(arguments=ReadFileArguments(path="helper.py")))
        self.service = self.cls(MemoryStore(self.directory.name))
        self.assertEqual(self.service.pending_actions(self.sid)[0], action)
        with patch("orchestrator.service.debug_direct") as llm:
            self.assertEqual(self.service.run_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
            llm.assert_not_called()
        result = ReadFileResult(file=SourceFile(path="helper.py", content="helper", content_hash="abc"))
        completed = self.service.submit_action_result(self.sid, action.action_id, result)
        self.assertEqual(self.service.submit_action_result(self.sid, action.action_id, result), completed)
        self.assertEqual(self.service.get_session(self.sid).status, DebugStage.CREATED)
        with patch("orchestrator.service.debug_direct", return_value="Answer") as llm:
            self.service.run_session(self.sid)
            from agents.direct_debugger import build_prompt
            prompt = build_prompt(llm.call_args.kwargs['problem'], llm.call_args.kwargs['context'])
            self.assertIn("Fix division", prompt)
            self.assertIn("unsaved", prompt)
            self.assertIn("helper", prompt)

    def test_multiple_actions_error_and_cancel(self):
        a = self.service.request_action(self.sid, ReadFileAction(arguments=ReadFileArguments(path="a.py")))
        b = self.service.request_action(self.sid, CoverageAction())
        with self.assertRaises(ValueError):
            self.service.submit_action_result(self.sid, a.action_id, CoverageResult(tests=[], source_snapshot_id="disk"))
        with self.assertRaises(ValueError):
            self.service.submit_action_result(self.sid, a.action_id, ReadFileResult(file=SourceFile(path="b.py", content="")))
        self.service.submit_action_result(self.sid, a.action_id, ActionError(code="not_found", message="Missing"))
        self.assertEqual(self.service.get_session(self.sid).status, DebugStage.WAITING_FOR_CONTEXT)
        self.service.cancel_session(self.sid)
        self.assertEqual(self.service.pending_actions(self.sid), [])
        with self.assertRaises(ValueError):
            self.service.submit_action_result(self.sid, b.action_id, CoverageResult(tests=[], source_snapshot_id="disk"))

    def test_paths(self):
        for path in ("../secret", "C:\\secret", "/secret", "a/../b", "file:///secret"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                ReadFileArguments(path=path)

    def test_http_poll_submit_and_errors(self):
        from fastapi.testclient import TestClient
        from app import app
        with patch("api.frontend.orchestrator", self.service), TestClient(app) as client:
            base = f"/debug/sessions/{self.sid}"
            action = self.service.request_action(self.sid, CoverageAction())
            self.assertEqual(client.get(base + "/actions").json()[0]["action_id"], action.action_id)
            endpoint = base + f"/actions/{action.action_id}/result"
            payload = {"result": {"type": "run_tests_with_coverage", "tests": [], "source_snapshot_id": "disk"}}
            self.assertEqual(client.post(endpoint, json={"result": {"type": "invalid"}}).status_code, 422)
            self.assertEqual(client.post(endpoint, json=payload).status_code, 200)
            self.assertEqual(client.post(endpoint, json=payload).status_code, 200)
            self.assertEqual(client.get(base + "/actions").json(), [])
            self.assertEqual(client.post(endpoint, json={"result": {"type": "error", "code": "x", "message": "x"}}).status_code, 409)
            self.assertEqual(client.get("/debug/sessions/missing/actions").status_code, 404)
