"""JSON checkpoints and explicit step summaries for a single-process debugger."""

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from orchestrator.state import DebugSession


class MemoryEntryType(str, Enum):
    OBSERVATION = "observation"
    TOOL_RESULT = "tool_result"
    HYPOTHESIS = "hypothesis"
    DECISION = "decision"
    USER_CLARIFICATION = "user_clarification"
    VERIFICATION = "verification"
    REFLECTION = "reflection"


class MemoryEntry(BaseModel):
    # Default keeps existing callers and saved files without a type readable.
    type: MemoryEntryType = MemoryEntryType.OBSERVATION
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    step: str
    summary: str
    result: str


class SessionMemory(BaseModel):
    schema_version: int = 1
    session: DebugSession
    entries: list[MemoryEntry] = Field(default_factory=list)


class MemoryStore:
    """One file per session. Use a database/locking for concurrent writers."""

    def __init__(self, directory: str | Path = "session_memory"):
        self.directory = Path(directory)

    def _path(self, session_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", session_id):
            raise ValueError("Invalid session ID")
        return self.directory / f"{session_id}.json"

    def load(self, session_id: str) -> SessionMemory:
        memory = SessionMemory.model_validate_json(
            self._path(session_id).read_text(encoding="utf-8")
        )
        if memory.schema_version != 1:
            raise ValueError("Unsupported memory schema version")
        if memory.session.session_id != session_id:
            raise ValueError("Memory session ID does not match filename")
        return memory

    def save(self, session: DebugSession, entry: MemoryEntry | None = None) -> None:
        path = self._path(session.session_id)
        try:
            memory = self.load(session.session_id)
        except FileNotFoundError:
            memory = SessionMemory(session=session)
        memory.session = session
        if entry is not None:
            memory.entries.append(entry)
        self.directory.mkdir(parents=True, exist_ok=True)
        # Replace atomically so an interrupted write cannot leave partial JSON.
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.directory,
                suffix=".tmp", delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(memory.model_dump_json(indent=2))
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def prompt_context(self, session_id: str, max_chars: int = 12000) -> str:
        """Include newest complete entries within a character budget."""
        if max_chars < 2:
            raise ValueError("max_chars must be at least 2")
        memory = self.load(session_id)
        selected: list[dict] = []
        for entry in reversed(memory.entries):
            candidate = [entry.model_dump(mode="json"), *selected]
            if len(json.dumps(candidate, ensure_ascii=False)) > max_chars:
                break
            selected = candidate
        return json.dumps(selected, ensure_ascii=False)
