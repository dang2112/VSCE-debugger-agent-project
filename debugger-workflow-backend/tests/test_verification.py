import difflib
from pathlib import Path
import tempfile
import unittest

from orchestrator.state import (RepairContext, RootCauseHypothesis, SourceFile, GeneratedPatch,
                                VerificationStatus, TestStageStatus)
from orchestrator.repair_config import RepairConfig
from tools.patches import source_hash
from tools.verification import VerificationService

ORIGINAL = 'def ratio(a, b):\n    return a // b\n'


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'project'
        (self.workspace / 'tests').mkdir(parents=True)
        (self.workspace / 'calc.py').write_text(ORIGINAL)
        (self.workspace / 'tests' / 'test_calc.py').write_text(
            'from calc import ratio\n\ndef test_fraction():\n    assert ratio(3, 2) == 1.5\n\ndef test_exact():\n    assert ratio(4, 2) == 2\n')
        self.config = RepairConfig(enabled=True)
        self.context = RepairContext(hypothesis=RootCauseHypothesis(summary='Floor division'),
            relevant_files=[SourceFile(path='calc.py', content=ORIGINAL)],
            editable_paths=['calc.py'], source_hashes={'calc.py': source_hash(ORIGINAL)})
        self.verifier = VerificationService(self.root / 'artifacts')

    def snapshot(self):
        return self.verifier.create_snapshot(str(self.workspace), self.context, self.config)

    def patch(self, content):
        diff = ''.join(difflib.unified_diff(ORIGINAL.splitlines(True), content.splitlines(True),
                                          fromfile='a/calc.py', tofile='b/calc.py'))
        return GeneratedPatch(diff=diff, base_hashes={'calc.py': source_hash(ORIGINAL)})

    def test_overfitted_fix_fails_full_suite_and_stale_hash_is_unverified(self):
        snapshot = self.snapshot()
        baseline = self.verifier.reproduce(snapshot, ['tests/test_calc.py::test_fraction'], self.config)
        self.assertEqual(baseline.status, TestStageStatus.FAILED)
        candidate = self.patch('def ratio(a, b):\n    return 1.5\n')
        result = self.verifier.verify(snapshot, candidate, ['tests/test_calc.py::test_fraction'], baseline, self.config)
        self.assertEqual(result.failing_tests.status, TestStageStatus.PASSED)
        self.assertEqual(result.full_suite.status, TestStageStatus.FAILED)
        self.assertEqual(result.overall_status, VerificationStatus.FAILED)
        candidate.base_hashes['calc.py'] = 'wrong'
        stale = self.verifier.verify(snapshot, candidate, ['tests/test_calc.py::test_fraction'], baseline, self.config)
        self.assertEqual(stale.overall_status, VerificationStatus.UNVERIFIED)
        self.assertFalse(stale.patch_applied)
        self.assertEqual((self.workspace / 'calc.py').read_text(), ORIGINAL)

    def test_fixture_errors_and_timeouts_are_not_test_failures(self):
        (self.workspace / 'tests' / 'conftest.py').write_text('raise RuntimeError("broken test environment")\n')
        snapshot = self.snapshot()
        baseline = self.verifier.reproduce(snapshot, [], self.config)
        self.assertEqual(baseline.status, TestStageStatus.ERROR)
        run, workspace = self.verifier._copy(snapshot, 'timeout-check')
        timeout = self.verifier.run_tests(workspace, ['tests'], run, 'timeout', .05)
        self.assertEqual(timeout.status, TestStageStatus.TIMED_OUT)

    def test_tests_that_mutate_captured_inputs_cannot_claim_success(self):
        (self.workspace / 'tests' / 'test_calc.py').write_text(
            'from pathlib import Path\nfrom calc import ratio\n\ndef test_fraction():\n'
            '    assert ratio(3, 2) == 1.5\n'
            '    p = Path("calc.py")\n    p.write_text(p.read_text() + "# changed by test\\n")\n')
        snapshot = self.snapshot()
        baseline = self.verifier.reproduce(snapshot, [], self.config)
        result = self.verifier.verify(snapshot, self.patch(ORIGINAL.replace('//', '/')),
            ['tests/test_calc.py::test_fraction'], baseline, self.config)
        self.assertEqual(result.overall_status, VerificationStatus.UNVERIFIED)
        self.assertIn('modified a captured input', result.error)
        self.assertEqual((self.workspace / 'calc.py').read_text(), ORIGINAL)
