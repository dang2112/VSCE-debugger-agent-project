"""Copy-on-write verification: baseline reproduction, strict patch apply, pytest checks.

Filesystem isolation protects user edits; executing project tests is not a security sandbox.
"""
import json
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

from orchestrator.actions import ReadFileArguments
from orchestrator.state import (VerificationResult, VerificationStageResult, VerificationStatus, TestStageStatus)
from tools.filesystem import workspace_root, resolve_path, scan_workspace
from tools.patches import apply_diff, source_hash
from tools.processes import PythonProcessRunner


def not_run(reason='Not run'):
    return VerificationStageResult(status=TestStageStatus.NOT_RUN, reason=reason)


class VerificationService:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.python = os.environ.get('VERIFICATION_PYTHON_EXECUTABLE', os.environ.get('SBFL_PYTHON_EXECUTABLE', sys.executable))

    def _snapshot(self, snapshot_id):
        if len(snapshot_id) != 32 or any(c not in '0123456789abcdef' for c in snapshot_id):
            raise ValueError('Invalid verification snapshot ID')
        return self.directory / snapshot_id

    def create_snapshot(self, workspace_path, repair_context, config, is_cancelled=lambda: False):
        root = workspace_root(workspace_path)
        inventory = scan_workspace(root)
        if inventory['scan_truncated'] or inventory['errors']:
            raise ValueError('Workspace snapshot discovery is incomplete; verification refused')
        snapshot_id = uuid4().hex
        directory = self._snapshot(snapshot_id)
        base = directory / 'baseline'
        base.mkdir(parents=True)
        total = count = 0
        manifest = {}
        for entry in inventory['entries']:
            if is_cancelled():
                raise RuntimeError('Verification cancelled')
            if entry['kind'] != 'file':
                continue
            source = resolve_path(root, entry['path'])
            if source.is_relative_to(self.directory):
                continue
            with source.open('rb') as stream:
                data = stream.read(min(5000001, config.max_snapshot_bytes + 1))
            total += len(data)
            count += 1
            if len(data) > 5000000 or total > config.max_snapshot_bytes or count > config.max_snapshot_files:
                raise ValueError('Workspace snapshot exceeds the configured verification copy budget')
            target = base / entry['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest[entry['path']] = hashlib.sha256(data).hexdigest()
        for file in repair_context.relevant_files:
            path = ReadFileArguments(path=file.path).path
            # Existing files only: an editor snapshot must map to a copied source.
            target = base / path
            if not target.is_file():
                raise ValueError('Repair snapshot source is missing or excluded: ' + path)
            data = file.content.encode('utf-8')
            total += len(data) - target.stat().st_size
            if total > config.max_snapshot_bytes:
                raise ValueError('Editor overlays exceed the verification snapshot budget')
            target.write_bytes(data)
            manifest[path] = source_hash(file.content)
        metadata = {'snapshot_id': snapshot_id, 'files': manifest,
                    'source_hashes': repair_context.source_hashes,
                    'source_basis': 'isolated disk copy with supplied editor snapshots overlaid',
                    'excluded': inventory['ignore_policy']}
        (directory / 'manifest.json').write_text(json.dumps(metadata), encoding='utf-8')
        return snapshot_id

    def _copy(self, snapshot_id, label):
        directory = self._snapshot(snapshot_id)
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        base = directory / 'baseline'
        for path, digest in manifest['files'].items():
            target = resolve_path(base, path)
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError('Verification baseline changed after capture: ' + path)
        run = directory / (label + '-' + uuid4().hex)
        shutil.copytree(directory / 'baseline', run / 'workspace')
        return run, run / 'workspace'

    @staticmethod
    def _selectors(workspace, selectors):
        if not selectors:
            raise ValueError('No pytest selectors configured')
        for selector in selectors:
            path = selector.split('::', 1)[0]
            resolve_path(workspace, path)
        return selectors

    def run_tests(self, workspace, selectors, run_directory, label, timeout, is_cancelled=lambda: False):
        results = run_directory / (label + '.json')
        log = run_directory / (label + '.log')
        try:
            self._selectors(workspace, selectors)
            env = os.environ.copy()
            shutil.copyfile(Path(__file__).with_name('verification_plugin.py'), run_directory / '_debugger_verification_plugin.py')
            env['PYTHONPATH'] = os.pathsep.join([str(run_directory), str(workspace / 'src'), str(workspace)])
            env['PYTHONPYCACHEPREFIX'] = str(run_directory / 'pycache')
            env['PYTHONIOENCODING'] = 'utf-8'
            env['DEBUGGER_TEST_RESULTS'] = str(results)
            env.pop('PYTEST_ADDOPTS', None)
            env.pop('PYTEST_PLUGINS', None)
            args = ['-m', 'pytest', '--rootdir', str(workspace), '-p', 'no:cacheprovider', '-o', 'addopts=', '-p', '_debugger_verification_plugin', '-q', '--', *selectors]
            code = PythonProcessRunner(self.python)._execute(args, workspace, env, log, timeout, is_cancelled)
            with log.open('r', encoding='utf-8', errors='replace') as stream:
                output = stream.read(16000)
            payload = json.loads(results.read_text(encoding='utf-8')) if results.is_file() else {}
            outcomes = payload.get('outcomes', {})
            command = subprocess.list2cmdline([self.python, *args])
            if code not in (0, 1) or not outcomes or 'error' in outcomes.values():
                return VerificationStageResult(status=TestStageStatus.ERROR, exit_code=code, output=output,
                    command=command, outcomes=outcomes, reason='Test infrastructure, collection, or fixture error')
            if code == 1 and 'failed' not in outcomes.values():
                return VerificationStageResult(status=TestStageStatus.ERROR, exit_code=code, output=output,
                    command=command, outcomes=outcomes, reason='pytest failed without a recorded call-phase failure')
            if not any(o in ('passed', 'failed') for o in outcomes.values()):
                return VerificationStageResult(status=TestStageStatus.ERROR, exit_code=code, output=output,
                    command=command, outcomes=outcomes, reason='No tests actually executed')
            status = TestStageStatus.FAILED if 'failed' in outcomes.values() else TestStageStatus.PASSED
            return VerificationStageResult(status=status, exit_code=code, output=output, command=command, outcomes=outcomes)
        except TimeoutError as exc:
            return VerificationStageResult(status=TestStageStatus.TIMED_OUT, reason=str(exc))
        except (ValueError, OSError, RuntimeError) as exc:
            if is_cancelled():
                raise RuntimeError('Verification cancelled') from exc
            return VerificationStageResult(status=TestStageStatus.ERROR, reason=str(exc))

    def reproduce(self, snapshot_id, failing_tests, config, is_cancelled=lambda: False):
        run, workspace = self._copy(snapshot_id, 'reproduce')
        return self.run_tests(workspace, failing_tests or config.test_targets, run, 'baseline', config.timeout_seconds, is_cancelled)

    def verify(self, snapshot_id, patch, reproduced_tests, baseline, config, is_cancelled=lambda: False):
        result = VerificationResult(failing_tests=not_run(), regression_tests=not_run(), full_suite=not_run(),
            overall_status=VerificationStatus.UNVERIFIED, baseline=baseline, snapshot_id=snapshot_id)
        if baseline.status != TestStageStatus.FAILED or not reproduced_tests:
            result.error = 'Original failure was not reproduced'
            return result
        try:
            manifest = json.loads((self._snapshot(snapshot_id) / 'manifest.json').read_text(encoding='utf-8'))
            if not patch.base_hashes or any(manifest['source_hashes'].get(p) != h for p, h in patch.base_hashes.items()):
                raise ValueError('Patch source hashes do not match the verification snapshot')
            run, workspace = self._copy(snapshot_id, 'candidate')
            sources = {p: (workspace / p).read_bytes().decode('utf-8') for p in patch.base_hashes}
            if any(source_hash(sources[p]) != h for p, h in patch.base_hashes.items()):
                raise ValueError('Snapshot source content changed after capture')
            updates = apply_diff(patch.diff, sources)
            if set(updates) != set(patch.base_hashes):
                raise ValueError('Patch paths do not match its bound source hashes')
            for path, content in updates.items():
                (workspace / path).write_bytes(content.encode('utf-8'))
            result.patch_applied = True
        except (ValueError, OSError) as exc:
            result.error = str(exc)
            return result
        result.failing_tests = self.run_tests(workspace, reproduced_tests, run, 'failing-tests', config.timeout_seconds, is_cancelled)
        if result.failing_tests.status == TestStageStatus.PASSED and any(
            result.failing_tests.outcomes.get(test) != 'passed' for test in reproduced_tests
        ):
            result.failing_tests.status = TestStageStatus.ERROR
            result.failing_tests.reason = 'Not every reproduced failure actually passed (missing or skipped tests)'
        if result.failing_tests.status == TestStageStatus.PASSED and config.regression_tests:
            result.regression_tests = self.run_tests(workspace, config.regression_tests, run, 'regression', config.timeout_seconds, is_cancelled)
        checks = [result.failing_tests] + ([result.regression_tests] if config.regression_tests else [])
        if all(c.status == TestStageStatus.PASSED for c in checks) and config.run_full_suite:
            result.full_suite = self.run_tests(workspace, config.test_targets, run, 'full-suite', config.timeout_seconds, is_cancelled)
            checks.append(result.full_suite)
        expected = {**manifest['files'], **{p: source_hash(c) for p, c in updates.items()}}
        try:
            for path, digest in expected.items():
                target = resolve_path(workspace, path)
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError('Tests modified a captured input file: ' + path)
        except (ValueError, OSError) as exc:
            result.overall_status = VerificationStatus.UNVERIFIED
            result.error = str(exc)
            return result
        if any(c.status in (TestStageStatus.ERROR, TestStageStatus.TIMED_OUT) for c in checks):
            result.overall_status = VerificationStatus.UNVERIFIED
            result.error = 'Verification incomplete due to infrastructure error or timeout'
        elif any(c.status == TestStageStatus.FAILED for c in checks):
            result.overall_status = VerificationStatus.FAILED
        elif all(c.status == TestStageStatus.PASSED for c in checks):
            result.overall_status = VerificationStatus.PASSED
        return result
