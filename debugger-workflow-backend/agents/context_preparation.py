"""Bounded source evidence and conservative traceback fallback retrieval."""
import hashlib
from pathlib import Path
import re

from orchestrator.actions import ReadFileArguments
from orchestrator.state import DebugContext, EvidenceItem, EvidenceType, SourceFile


def source_evidence(file: SourceFile, limit: int, origin: str) -> EvidenceItem:
    return EvidenceItem(
        type=EvidenceType.SOURCE_CODE, source=origin, path=file.path,
        content=file.content[:limit], metadata={
            "uri": file.uri, "document_version": file.document_version,
            "is_dirty": file.is_dirty, "provided_content_hash": file.content_hash,
            "sha256_utf8": hashlib.sha256(file.content.encode("utf-8")).hexdigest(),
            "original_chars": len(file.content), "truncated": len(file.content) > limit,
            "source_basis": "editor snapshot; may differ from tested disk contents",
        },
    )


def bounded_context(context: DebugContext, per_file: int, total: int) -> tuple[DebugContext, list[dict]]:
    files = list(context.files)
    if context.active_file:
        files = [context.active_file] + [f for f in files if f.path != context.active_file.path]
    selected = []
    notes = []
    remaining = total
    for file in files:
        take = min(len(file.content), per_file, remaining)
        if take < len(file.content):
            notes.append({"path": file.path, "included_chars": take,
                          "original_chars": len(file.content), "truncated": True})
        if remaining <= 0:
            continue
        selected.append(file.model_copy(update={"content": file.content[:take]}))
        remaining -= take
    return context.model_copy(update={"active_file": None, "files": selected}), notes


def traceback_paths(error_log: str | None, workspace_path: str | None) -> list[str]:
    paths = []
    workspace = Path(workspace_path).resolve() if workspace_path else None
    for raw in reversed(re.findall(r'File [\"\']([^\"\']+\.py)[\"\']', error_log or "")):
        try:
            path = Path(raw)
            if path.is_absolute():
                if workspace is None:
                    continue
                raw = path.resolve().relative_to(workspace).as_posix()
            relative = ReadFileArguments(path=raw).path
            if workspace and not (workspace / relative).resolve().is_relative_to(workspace):
                continue
            if relative not in paths:
                paths.append(relative)
        except (ValueError, OSError):
            continue
    return paths
