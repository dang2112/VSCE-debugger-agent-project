"""Bounded, read-only workspace discovery; source contents are never loaded here."""
from collections import Counter, deque
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from orchestrator.actions import ReadFileArguments

DOCUMENT_SUFFIXES = {".md", ".markdown"}
EXCLUDED_NAMES = {"node_modules", "venv", ".venv", "__pycache__", "dist", "build", "coverage", "session_memory", "target"}
MAX_SCANNED_ENTRIES = 10000


class ProjectStructureArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = "."
    max_depth: int = Field(default=3, ge=1, le=10)
    offset: int = Field(default=0, ge=0, le=10000)
    limit: int = Field(default=200, ge=1, le=500)
    documents_only: bool = False


def workspace_root(workspace_path: str | None) -> Path:
    if not workspace_path:
        raise ValueError("This tool requires a backend-accessible context.workspace_path")
    root = Path(workspace_path).resolve()
    if not root.is_dir():
        raise ValueError("Session workspace is not available on the backend")
    return root


def hidden(name: str) -> bool:
    return name in EXCLUDED_NAMES or (name.startswith('.') and name != '.github')


def resolve_path(root: Path, relative: str) -> Path:
    if relative != '.':
        relative = ReadFileArguments(path=relative).path
    path = root / relative
    current = root
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink() or hidden(part):
            raise ValueError("Hidden, generated, and symlink paths are excluded")
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Path escapes the session workspace")
    return resolved


def ignore_rules(directory: Path):
    file = directory / '.gitignore'
    if file.is_file() and not file.is_symlink():
        from pathspec import GitIgnoreSpec
        with file.open('r', encoding='utf-8', errors='replace') as stream:
            text = stream.read(65537)
        if len(text) > 65536:
            raise ValueError("Ignore file exceeds 64 KiB")
        return GitIgnoreSpec.from_lines(text.splitlines())
    return None


def is_ignored(path: Path, root: Path, rules: list, directory: bool) -> bool:
    ignored = False
    for base, spec in rules:
        relative = path.relative_to(base).as_posix() + ('/' if directory else '')
        match = spec.check_file(relative).include
        if match is not None:
            ignored = match
    return ignored


def scan_workspace(root: Path, max_depth: int = 32) -> dict:
    entries, errors = [], []
    queue = deque([(root, 0, [])])
    visited = 0
    truncated = False
    while queue and not truncated:
        directory, depth, parents = queue.popleft()
        try:
            spec = ignore_rules(directory)
            rules = parents + ([(directory, spec)] if spec else [])
            # Inspect at most the scan budget; a huge flat directory stays bounded.
            children = []
            import os
            with os.scandir(directory) as iterator:
                for child in iterator:
                    visited += 1
                    if visited > MAX_SCANNED_ENTRIES:
                        truncated = True
                        break
                    children.append(child)
            for child in sorted(children, key=lambda c: c.name.casefold()):
                if hidden(child.name) or child.is_symlink():
                    continue
                path = Path(child.path)
                is_dir = child.is_dir(follow_symlinks=False)
                if is_ignored(path, root, rules, is_dir):
                    continue
                if not is_dir and not child.is_file(follow_symlinks=False):
                    continue
                entries.append({'path': path.relative_to(root).as_posix(),
                                'kind': 'directory' if is_dir else 'file',
                                'is_document': not is_dir and path.suffix.lower() in DOCUMENT_SUFFIXES,
                                'depth': depth + 1})
                if is_dir and depth + 1 < max_depth:
                    queue.append((path, depth + 1, rules))
        except OSError as exc:
            errors.append({'path': directory.relative_to(root).as_posix(), 'error': type(exc).__name__})
    return {'entries': entries, 'scan_truncated': truncated,
            'depth_limit': max_depth, 'errors': errors,
            'ignore_policy': 'built-in exclusions plus nested .gitignore; no symlink traversal'}


def project_structure(workspace_path: str | None, arguments: ProjectStructureArguments) -> dict:
    root = workspace_root(workspace_path)
    scope = resolve_path(root, arguments.path)
    if not scope.is_dir():
        raise ValueError("Structure scope must be a directory")
    # Scan from the root so parent ignore rules also apply to narrowed scopes.
    inventory = scan_workspace(root, max_depth=arguments.max_depth + len(scope.relative_to(root).parts))
    prefix = scope.relative_to(root).as_posix()
    entries = [e for e in inventory.pop('entries') if
               (prefix == '.' or e['path'].startswith(prefix + '/'))
               and (not arguments.documents_only or e['is_document'])]
    return {**inventory, 'scope': arguments.path, 'total_visible_entries': len(entries),
            'file_types': dict(Counter(Path(e['path']).suffix.lower() or '<no extension>' for e in entries if e['kind'] == 'file')),
            'entries': entries[arguments.offset:arguments.offset + arguments.limit],
            'has_more': arguments.offset + arguments.limit < len(entries), 'source_contents_loaded': False}
