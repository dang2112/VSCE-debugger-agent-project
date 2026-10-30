import json
import os
import tempfile
import unittest
from unittest.mock import patch

from orchestrator.state import DebugContext, DebugProblem, DebugSession, FailureType
from tools.memorysystem import MemoryEntry, MemoryEntryType, MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_entry_types_and_legacy_files(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            session = DebugSession(
                problem=DebugProblem(failure_type=FailureType.RUNTIME_ERROR),
                context=DebugContext(),
            )
            for entry_type in MemoryEntryType:
                store.save(session, MemoryEntry(
                    type=entry_type, step="test", summary="Summary", result="Result",
                ))
            entries = json.loads(store.prompt_context(session.session_id))
            self.assertEqual([entry["type"] for entry in entries], [t.value for t in MemoryEntryType])
            path = store.directory / f"{session.session_id}.json"
            legacy = json.loads(path.read_text(encoding="utf-8"))
            del legacy["entries"][0]["type"]
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertEqual(store.load(session.session_id).entries[0].type, MemoryEntryType.OBSERVATION)
        with self.assertRaises(ValueError):
            MemoryEntry(type="unknown", step="test", summary="Summary", result="Result")

    def test_checkpoint_history_and_prompt_survive_new_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            session = DebugSession(
                problem=DebugProblem(failure_type=FailureType.RUNTIME_ERROR),
                context=DebugContext(),
            )
            store.save(session, MemoryEntry(step="analysis", summary="Found cause", result="A"))
            session.final_explanation = "Fixed"
            store.save(session, MemoryEntry(step="verification", summary="Passed", result="B"))
            restored = MemoryStore(directory)
            memory = restored.load(session.session_id)
            self.assertEqual(memory.session, session)
            self.assertEqual(len(memory.entries), 2)
            self.assertEqual(json.loads(restored.prompt_context(session.session_id))[-1]["result"], "B")
            self.assertEqual(restored.prompt_context(session.session_id, max_chars=2), "[]")

    def test_rejects_path_traversal_and_corrupt_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            with self.assertRaises(ValueError):
                store.load("../outside")
            path = store.directory / "broken.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaises(ValueError):
                store.load("broken")

    def test_orchestrator_restores_session_and_passes_history_to_llm(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("google.genai.Client"):
                from orchestrator.service import DebugOrchestrator
        from api.schemas import CreateDebugSessionRequest

        with tempfile.TemporaryDirectory() as directory:
            store = MemoryStore(directory)
            orchestrator = DebugOrchestrator(store)
            created = orchestrator.create_session(CreateDebugSessionRequest(
                problem=DebugProblem(failure_type=FailureType.RUNTIME_ERROR),
                context=DebugContext(),
            ))
            session = store.load(created.session_id).session
            store.save(session, MemoryEntry(step="evidence", summary="Collected", result="Traceback"))
            restarted = DebugOrchestrator(MemoryStore(directory))
            with patch("orchestrator.service.debug_direct", return_value="Use a guard") as llm:
                restarted.run_session(created.session_id)
                self.assertIn("Traceback", llm.call_args.kwargs["memory_context"])
            restored = DebugOrchestrator(MemoryStore(directory))
            self.assertEqual(restored.get_result(created.session_id).explanation, "Use a guard")
            self.assertEqual(len(store.load(created.session_id).entries), 2)


if __name__ == "__main__":
    unittest.main()
