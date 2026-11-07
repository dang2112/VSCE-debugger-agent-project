import json
from pathlib import Path
import shutil
import os
import tempfile
import unittest

from tools.sbfl import RunSBFLArguments, SBFLService


class SBFLAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / "workspace"
        clone = Path(__file__).resolve().parents[1] / "tools" / "sbfl"
        shutil.copytree(clone / "src" / "shopping", self.workspace / "src" / "shopping")
        shutil.copytree(clone / "tests" / "demo", self.workspace / "tests")
        self.service = SBFLService(self.root / "artifacts")

    def test_real_engine_demo_ranking_and_trace(self):
        result = self.service.run(str(self.workspace), RunSBFLArguments(source_root="src/shopping"))
        self.assertEqual(result.total_tests, 8)
        self.assertEqual(result.total_failing, 2)
        self.assertEqual(result.pytest_exit_code, 1)
        self.assertEqual(result.localization.candidates[0].path, "src/shopping/discount.py")
        self.assertIn("loyalty_discount_rate", result.localization.candidates[0].function)
        tests = self.service.list_tests(result.run_id)
        failing = next(t for t in tests['tests'] if t['outcome'] == 'failed')
        trace = self.service.trace(result.run_id, failing['nodeid'], limit=1)
        self.assertEqual(len(trace['invocations']), 1)
        self.assertGreater(trace['total_invocations'], 0)
        artifact = self.root / "artifacts" / result.run_id / "result.json"
        self.assertEqual(json.loads(artifact.read_text())['run_id'], result.run_id)

    def test_no_failures_and_collection_error(self):
        (self.workspace / "tests" / "test_ok.py").write_text('def test_ok():\n    assert True\n')
        result = self.service.run(str(self.workspace), RunSBFLArguments(test_ids=['tests/test_ok.py']))
        self.assertEqual(result.status, 'no_eligible_failures')
        self.assertEqual(result.localization.candidates, [])
        with self.assertRaisesRegex(RuntimeError, 'collection failed'):
            self.service.run(str(self.workspace), RunSBFLArguments(test_ids=['tests/missing.py']))

    def test_workspace_boundaries(self):
        for arguments in ({'source_root': '../'}, {'test_ids': ['../test.py']}, {'test_ids': ['C:/test.py']}):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.service.run(str(self.workspace), RunSBFLArguments(**arguments))
        with self.assertRaises(ValueError):
            self.service.run(None, RunSBFLArguments())
        with self.assertRaises(ValueError):
            self.service.list_tests('../secret')

    def test_wall_clock_timeout(self):
        environment = os.environ.copy()
        with self.assertRaises(TimeoutError):
            self.service._execute(['-c', 'import time; time.sleep(30)'], self.workspace,
                                  environment, self.root / 'timeout.log', 0.1)

    def test_running_process_can_be_cancelled(self):
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            self.service._execute(['-c', 'import time; time.sleep(30)'], self.workspace,
                                  os.environ.copy(), self.root / 'cancel.log', 30, lambda: True)
