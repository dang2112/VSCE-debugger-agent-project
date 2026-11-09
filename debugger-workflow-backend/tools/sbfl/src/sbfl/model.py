from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class LocalChange:
    line: int
    name: str
    old: str | None
    new: str | None


@dataclass(slots=True)
class InvocationBlock:
    call_id: int
    parent_call_id: int | None
    function_id: str
    function_name: str
    file: str
    first_line: int
    arguments: dict[str, str] = field(default_factory=dict)
    executed_lines: list[int] = field(default_factory=list)
    local_changes: list[LocalChange] = field(default_factory=list)
    return_value: str | None = None
    exception: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TestEvidence:
    nodeid: str
    outcome: str = "unknown"
    covered_functions: set[str] = field(default_factory=set)
    invocations: list[InvocationBlock] = field(default_factory=list)
    failure: dict[str, str] | None = None
    excluded_from_ranking: bool = False
    exclusion_reason: str | None = None
    network_attempts: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeid": self.nodeid,
            "outcome": self.outcome,
            "covered_functions": sorted(self.covered_functions),
            "invocations": [block.to_dict() for block in self.invocations],
            "failure": self.failure,
            "excluded_from_ranking": self.excluded_from_ranking,
            "exclusion_reason": self.exclusion_reason,
            "network_attempts": self.network_attempts,
        }
