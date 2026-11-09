import os
import tempfile
import unittest
from unittest.mock import patch

from api.schemas import CreateDebugSessionRequest
from orchestrator.state import DebugContext, DebugMode, DebugProblem, DebugStage, FailureType
from tools.memorysystem import MemoryEntry, MemoryEntryType, MemoryStore


class TwoThinkingTimesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
            with patch("google.genai.Client"):
                from orchestrator.service import DebugOrchestrator
        cls.orchestrator_class = DebugOrchestrator

    def make_session(self, directory):
        store = MemoryStore(directory)
        orchestrator = self.orchestrator_class(store)
        request = CreateDebugSessionRequest(
            mode="two-thinking-times",
            problem=DebugProblem(failure_type=FailureType.RUNTIME_ERROR, error_log="ZeroDivisionError"),
            context=DebugContext(),
        )
        self.assertEqual(request.mode, DebugMode.TWO_THINKING_TIMES)
        session_id = orchestrator.create_session(request).session_id
        return store, orchestrator, session_id

    def test_two_llm_calls_with_disk_round_trip_and_final_review(self):
        from agents.direct_debugger import client

        with tempfile.TemporaryDirectory() as directory:
            store, orchestrator, session_id = self.make_session(directory)
            initial = "Check divisor. " + "evidence " * 2000
            final = "Reasonably confident: guard against a zero divisor."

            def generate(**kwargs):
                if generate_mock.call_count == 1:
                    return type("Response", (), {"text": initial})()
                # The first answer must already be on disk before call two.
                memory = MemoryStore(directory).load(session_id)
                self.assertEqual(memory.entries[0].result, initial)
                self.assertEqual(memory.session.stage, DebugStage.REVIEWING_ANALYSIS)
                self.assertIn(initial, kwargs["contents"])
                self.assertIn("reasonably confident", kwargs["contents"])
                self.assertIn("ZeroDivisionError", kwargs["contents"])
                self.assertIn('"type": "hypothesis"', kwargs["contents"])
                for entry_type in MemoryEntryType:
                    self.assertIn(entry_type.value + ":", kwargs["config"].system_instruction)
                return type("Response", (), {"text": final})()

            with patch.object(client.models, "generate_content", side_effect=generate) as generate_mock:
                response = orchestrator.run_session(session_id)
                self.assertEqual(response.status, DebugStage.COMPLETED)
                orchestrator.run_session(session_id)
                self.assertEqual(generate_mock.call_count, 2)

            memory = store.load(session_id)
            self.assertEqual([entry.result for entry in memory.entries], [initial, final])
            self.assertEqual([entry.type for entry in memory.entries], [
                MemoryEntryType.HYPOTHESIS, MemoryEntryType.REFLECTION,
            ])
            restored = self.orchestrator_class(MemoryStore(directory))
            self.assertEqual(restored.get_result(session_id).explanation, final)

    def test_failed_review_preserves_initial_result(self):
        with tempfile.TemporaryDirectory() as directory:
            store, orchestrator, session_id = self.make_session(directory)
            with patch("orchestrator.service.debug_direct", return_value="Initial analysis"):
                with patch("orchestrator.service.review_debug_analysis", side_effect=RuntimeError("Review failed")):
                    with self.assertRaisesRegex(RuntimeError, "Review failed"):
                        orchestrator.run_session(session_id)
            memory = store.load(session_id)
            self.assertEqual(memory.session.stage, DebugStage.FAILED)
            self.assertEqual(memory.session.debug_error, "Review failed")
            self.assertEqual(memory.entries[0].result, "Initial analysis")
            self.assertIsNone(memory.session.final_explanation)

    def test_retry_review_without_repeating_analysis(self):
        for restart in (False, True):
            with self.subTest(restart=restart), tempfile.TemporaryDirectory() as directory:
                store, orchestrator, session_id = self.make_session(directory)
                with patch("orchestrator.service.debug_direct", return_value="Saved analysis") as initial:
                    with patch("orchestrator.service.review_debug_analysis", side_effect=RuntimeError("Temporary failure")):
                        with self.assertRaises(RuntimeError):
                            orchestrator.run_session(session_id)
                    self.assertEqual(initial.call_count, 1)
                if restart:
                    orchestrator = self.orchestrator_class(MemoryStore(directory))
                with patch("orchestrator.service.debug_direct") as initial:
                    with patch("orchestrator.service.review_debug_analysis", return_value="Reviewed answer") as review:
                        orchestrator.run_session(session_id)
                        initial.assert_not_called()
                        self.assertEqual(review.call_args.kwargs["previous_entry"].result, "Saved analysis")
                memory = store.load(session_id)
                self.assertEqual(len(memory.entries), 2)
                self.assertEqual(memory.session.stage, DebugStage.COMPLETED)
                self.assertIsNone(memory.session.debug_error)
                self.assertEqual(memory.session.final_explanation, "Reviewed answer")

    def test_retry_initial_failure_runs_both_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            store, orchestrator, session_id = self.make_session(directory)
            with patch("orchestrator.service.debug_direct", side_effect=RuntimeError("Unavailable")):
                with patch("orchestrator.service.review_debug_analysis") as review:
                    with self.assertRaises(RuntimeError):
                        orchestrator.run_session(session_id)
                    review.assert_not_called()
            self.assertEqual(store.load(session_id).entries, [])
            orchestrator = self.orchestrator_class(MemoryStore(directory))
            with patch("orchestrator.service.debug_direct", return_value="Initial") as initial:
                with patch("orchestrator.service.review_debug_analysis", return_value="Final") as review:
                    orchestrator.run_session(session_id)
                    initial.assert_called_once()
                    review.assert_called_once()
            self.assertEqual(len(store.load(session_id).entries), 2)

    def test_resume_interrupted_checkpoints(self):
        for mode, reviewed in ((DebugMode.DIRECT, False),
                               (DebugMode.TWO_THINKING_TIMES, False),
                               (DebugMode.TWO_THINKING_TIMES, True)):
            with self.subTest(mode=mode, reviewed=reviewed), tempfile.TemporaryDirectory() as directory:
                store, _, session_id = self.make_session(directory)
                session = store.load(session_id).session
                session.mode = mode
                session.stage = DebugStage.ROOT_CAUSE_ANALYSIS
                store.save(session, MemoryEntry(
                    type="hypothesis", step="root_cause_analysis",
                    summary="Initial", result="Saved initial",
                ))
                # An unrelated later entry must not be mistaken for the analysis.
                store.save(session, MemoryEntry(
                    type="tool_result", step="tool", summary="Tool", result="Other output",
                ))
                if reviewed:
                    session.stage = DebugStage.REVIEWING_ANALYSIS
                    store.save(session, MemoryEntry(
                        type="reflection", step="reviewing_analysis",
                        summary="Review", result="Saved review",
                    ))
                orchestrator = self.orchestrator_class(MemoryStore(directory))
                with patch("orchestrator.service.debug_direct") as initial:
                    with patch("orchestrator.service.review_debug_analysis", return_value="New review") as review:
                        orchestrator.run_session(session_id)
                        initial.assert_not_called()
                        if mode == DebugMode.TWO_THINKING_TIMES and not reviewed:
                            self.assertEqual(review.call_args.kwargs["previous_entry"].result, "Saved initial")
                        else:
                            review.assert_not_called()
                expected = "Saved initial" if mode == DebugMode.DIRECT else (
                    "Saved review" if reviewed else "New review")
                self.assertEqual(orchestrator.get_result(session_id).explanation, expected)
                self.assertEqual(len(store.load(session_id).entries),
                                 2 if mode == DebugMode.DIRECT else 3)


if __name__ == "__main__":
    unittest.main()
