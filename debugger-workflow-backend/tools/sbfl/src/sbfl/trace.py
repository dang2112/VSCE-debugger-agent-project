from __future__ import annotations

import inspect
import os
import threading
from pathlib import Path
from types import FrameType
from typing import Any, Callable

from sbfl.model import InvocationBlock, LocalChange, TestEvidence


TraceFn = Callable[[FrameType, str, Any], Any]
_MISSING = object()


def _safe_repr(value: Any, max_len: int = 200) -> str:
    """Represent runtime values without allowing one huge object to explode the trace."""
    try:
        text = repr(value)
    except Exception as exc:  # pragma: no cover - defensive
        text = f"<unrepresentable {type(value).__name__}: {exc}>"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _snapshot_locals(frame: FrameType, max_items: int = 30) -> dict[str, str]:
    result: dict[str, str] = {}
    for idx, (name, value) in enumerate(frame.f_locals.items()):
        if idx >= max_items:
            result["<truncated>"] = "..."
            break
        result[name] = _safe_repr(value)
    return result


class FunctionTraceRecorder:
    """Collect per-test function coverage and lightweight invocation blocks.

    This tracer is intentionally Phase-1 sized:
    - it records only frames whose file is under `source_root`,
    - it traces the current pytest thread,
    - it stores bounded repr() values rather than object references,
    - it records at most `max_local_changes` changes per invocation.
    """

    def __init__(
        self,
        nodeid: str,
        source_root: str | Path,
        *,
        max_local_changes: int = 50,
    ) -> None:
        self.nodeid = nodeid
        self.source_root = Path(source_root).resolve()
        self.max_local_changes = max_local_changes
        self.evidence = TestEvidence(nodeid=nodeid)
        self._next_call_id = 1
        self._frame_to_call_id: dict[int, int] = {}
        self._call_stack_by_thread: dict[int, list[int]] = {}
        self._block_by_call_id: dict[int, InvocationBlock] = {}
        self._locals_by_call_id: dict[int, dict[str, str]] = {}

    def _in_scope(self, frame: FrameType) -> bool:
        if frame.f_code.co_name in {"<genexpr>", "<listcomp>", "<dictcomp>", "<setcomp>"}:
            return False
        try:
            Path(frame.f_code.co_filename).resolve().relative_to(self.source_root)
            return True
        except ValueError:
            return False

    def _relative_file(self, frame: FrameType) -> str:
        path = Path(frame.f_code.co_filename).resolve()
        try:
            return path.relative_to(self.source_root.parent).as_posix()
        except ValueError:
            return path.name

    def _qualname(self, frame: FrameType) -> str:
        code = frame.f_code
        qualname = getattr(code, "co_qualname", code.co_name)
        module = frame.f_globals.get("__name__")
        if module:
            return f"{module}.{qualname}"
        return qualname

    def _function_id(self, frame: FrameType) -> str:
        return f"{self._relative_file(frame)}::{self._qualname(frame)}@{frame.f_code.co_firstlineno}"

    def _arguments(self, frame: FrameType) -> dict[str, str]:
        try:
            arg_info = inspect.getargvalues(frame)
        except Exception:  # pragma: no cover - defensive
            return {}

        result: dict[str, str] = {}
        names = list(arg_info.args)
        if arg_info.varargs:
            names.append(arg_info.varargs)
        if arg_info.keywords:
            names.append(arg_info.keywords)
        for name in names:
            if name in frame.f_locals:
                result[name] = _safe_repr(frame.f_locals[name])
        return result

    def _stack(self) -> list[int]:
        return self._call_stack_by_thread.setdefault(threading.get_ident(), [])

    def trace(self, frame: FrameType, event: str, arg: Any) -> TraceFn | None:
        # Returning ourselves for out-of-scope frames is necessary so Python can
        # still notify us when execution enters an in-scope callee later.
        if event == "call":
            if not self._in_scope(frame):
                return self.trace
            self._on_call(frame)
            return self.trace

        if not self._in_scope(frame):
            return self.trace

        if event == "line":
            self._on_line(frame)
        elif event == "return":
            self._on_return(frame, arg)
        elif event == "exception":
            self._on_exception(frame, arg)
        return self.trace

    def _on_call(self, frame: FrameType) -> None:
        call_id = self._next_call_id
        self._next_call_id += 1

        stack = self._stack()
        parent_call_id = stack[-1] if stack else None
        block = InvocationBlock(
            call_id=call_id,
            parent_call_id=parent_call_id,
            function_id=self._function_id(frame),
            function_name=self._qualname(frame),
            file=self._relative_file(frame),
            first_line=frame.f_code.co_firstlineno,
            arguments=self._arguments(frame),
        )
        self.evidence.covered_functions.add(block.function_id)
        self.evidence.invocations.append(block)
        self._frame_to_call_id[id(frame)] = call_id
        self._block_by_call_id[call_id] = block
        self._locals_by_call_id[call_id] = _snapshot_locals(frame)
        stack.append(call_id)

    def _on_line(self, frame: FrameType) -> None:
        call_id = self._frame_to_call_id.get(id(frame))
        if call_id is None:
            return
        block = self._block_by_call_id[call_id]
        if not block.executed_lines or block.executed_lines[-1] != frame.f_lineno:
            block.executed_lines.append(frame.f_lineno)

        if len(block.local_changes) >= self.max_local_changes:
            return

        old_snapshot = self._locals_by_call_id.get(call_id, {})
        new_snapshot = _snapshot_locals(frame)
        for name in sorted(set(old_snapshot) | set(new_snapshot)):
            old = old_snapshot.get(name, _MISSING)
            new = new_snapshot.get(name, _MISSING)
            if old == new:
                continue
            block.local_changes.append(
                LocalChange(
                    line=frame.f_lineno,
                    name=name,
                    old=None if old is _MISSING else str(old),
                    new=None if new is _MISSING else str(new),
                )
            )
            if len(block.local_changes) >= self.max_local_changes:
                break
        self._locals_by_call_id[call_id] = new_snapshot

    def _on_exception(self, frame: FrameType, arg: Any) -> None:
        call_id = self._frame_to_call_id.get(id(frame))
        if call_id is None:
            return
        exc_type, exc_value, _traceback = arg
        self._block_by_call_id[call_id].exception = {
            "type": getattr(exc_type, "__name__", str(exc_type)),
            "message": _safe_repr(exc_value),
            "line": str(frame.f_lineno),
        }

    def _on_return(self, frame: FrameType, value: Any) -> None:
        frame_id = id(frame)
        call_id = self._frame_to_call_id.pop(frame_id, None)
        if call_id is None:
            return

        block = self._block_by_call_id[call_id]
        block.return_value = _safe_repr(value)
        self._locals_by_call_id.pop(call_id, None)

        stack = self._stack()
        if stack and stack[-1] == call_id:
            stack.pop()
        else:  # defensive recovery if tracing was interrupted
            try:
                stack.remove(call_id)
            except ValueError:
                pass

    def finish(self) -> TestEvidence:
        return self.evidence
