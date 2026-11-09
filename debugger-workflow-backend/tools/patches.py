"""Strict unified-diff validation and in-memory application for existing Python files."""
import hashlib
from pathlib import PurePosixPath
import re

from orchestrator.actions import ReadFileArguments


HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?:.*)\n?$')


def source_hash(content: str) -> str:
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def editable_path(path: str) -> str:
    normalized = ReadFileArguments(path=path).path
    parts = PurePosixPath(normalized).parts
    if (not normalized.endswith('.py') or any(p.startswith('.') for p in parts)
            or any(p.lower() in {'tests', 'test', 'node_modules', 'venv', 'session_memory'} for p in parts)
            or parts[-1].lower() in {'conftest.py', 'setup.py', 'noxfile.py', 'toxfile.py', 'sitecustomize.py', 'usercustomize.py', 'pytest.py'}
            or parts[-1].lower().startswith('test_') or parts[-1].lower().endswith('_test.py')):
        raise ValueError('Patch targets must be application Python files, not tests/configuration: ' + path)
    return normalized


def apply_diff(diff: str, sources: dict[str, str]) -> dict[str, str]:
    """Return updated files only. No writes, fuzzy matching, new files, or deletions."""
    if not diff.strip() or len(diff) > 200000:
        raise ValueError('Patch must be a nonempty unified diff of at most 200000 characters')
    lines = diff.replace('\r\n', '\n').splitlines(keepends=True)
    updates = {}
    index = 0
    changed = 0
    while index < len(lines):
        if lines[index].startswith(('diff --git ', 'index ')):
            index += 1
            continue
        if not lines[index].startswith('--- a/'):
            raise ValueError('Expected --- a/path header; mode changes, binary patches and renames are unsupported')
        path = editable_path(lines[index][6:].rstrip('\n').split('\t', 1)[0])
        index += 1
        if index >= len(lines) or not lines[index].startswith('+++ b/'):
            raise ValueError('Expected +++ b/path header')
        new_path = lines[index][6:].rstrip('\n').split('\t', 1)[0]
        if new_path != path or path not in sources or path in updates:
            raise ValueError('Patch path is not a unique supplied source file: ' + path)
        index += 1
        source = sources[path]
        if ('\r' in source.replace('\r\n', '') or
                ('\r\n' in source and '\n' in source.replace('\r\n', ''))):
            raise ValueError('Mixed or unsupported source newline conventions')
        original = source.replace('\r\n', '\n').splitlines(keepends=True)
        output, cursor, hunks = [], 0, 0
        while index < len(lines) and lines[index].startswith('@@ '):
            match = HUNK.match(lines[index])
            if match is None:
                raise ValueError('Malformed hunk header')
            old_start, old_count, new_start, new_count = (int(match[1]), int(match[2] or 1), int(match[3]), int(match[4] or 1))
            target = old_start - 1 if old_count else old_start
            new_target = new_start - 1 if new_count else new_start
            if target < cursor or target > len(original) or len(output) + target - cursor != new_target:
                raise ValueError('Hunk offsets do not match the supplied snapshot')
            output.extend(original[cursor:target])
            cursor = target
            index += 1
            operations = []
            old_seen = new_seen = 0
            while index < len(lines):
                line = lines[index]
                if line.startswith('\\ No newline at end of file'):
                    if not operations or not operations[-1][1].endswith('\n'):
                        raise ValueError('Invalid no-newline marker')
                    operations[-1] = (operations[-1][0], operations[-1][1][:-1])
                    index += 1
                    continue
                if old_seen == old_count and new_seen == new_count:
                    break
                if not line or line[0] not in ' +-':
                    raise ValueError('Unexpected line within a hunk')
                kind, content = line[0], line[1:]
                operations.append((kind, content))
                old_seen += kind in ' -'
                new_seen += kind in ' +'
                if old_seen > old_count or new_seen > new_count:
                    raise ValueError('Hunk line counts are inconsistent')
                index += 1
            if (old_seen, new_seen) != (old_count, new_count):
                raise ValueError('Incomplete hunk')
            for kind, content in operations:
                if kind in ' -':
                    if cursor >= len(original) or original[cursor] != content:
                        raise ValueError(f'Hunk context mismatch in {path} at line {cursor + 1}')
                    cursor += 1
                if kind in ' +':
                    output.append(content)
                changed += kind in '+-'
            hunks += 1
        if not hunks:
            raise ValueError('File patch contains no hunks')
        output.extend(original[cursor:])
        updated = ''.join(output)
        if '\r\n' in sources[path]:
            updated = updated.replace('\n', '\r\n')
        updates[path] = updated
    if not changed or all(updates[path] == sources[path] for path in updates):
        raise ValueError('Patch makes no change')
    return updates
