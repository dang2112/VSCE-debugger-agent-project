"""Persisted extension actions. Paths are workspace-relative, never shell commands."""
from typing import Annotated, Literal
from pathlib import PurePosixPath, PureWindowsPath
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from orchestrator.snapshots import SourceFile


class ReadFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value: str) -> str:
        path = value.replace("\\", "/")
        if (PurePosixPath(path).is_absolute() or PureWindowsPath(value).drive
                or ".." in path.split("/") or ":" in path or "\x00" in path
                or path in (".", "")):
            raise ValueError("path must be workspace-relative without parent traversal")
        return path


class ReadFileAction(BaseModel):
    type: Literal["read_file"] = "read_file"
    arguments: ReadFileArguments


class CoverageArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runner: Literal["pytest"] = "pytest"
    test_ids: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=120, ge=1, le=1800)


class CoverageAction(BaseModel):
    type: Literal["run_tests_with_coverage"] = "run_tests_with_coverage"
    arguments: CoverageArguments = Field(default_factory=CoverageArguments)


ActionRequest = Annotated[ReadFileAction | CoverageAction, Field(discriminator="type")]


class ReadFileResult(BaseModel):
    type: Literal["read_file"] = "read_file"
    file: SourceFile


class TestCoverage(BaseModel):
    test_id: str
    outcome: Literal["passed", "failed", "skipped", "error"]
    covered_lines: dict[str, list[Annotated[int, Field(ge=1)]]] = Field(default_factory=dict)


class CoverageResult(BaseModel):
    type: Literal["run_tests_with_coverage"] = "run_tests_with_coverage"
    tests: list[TestCoverage]
    source_snapshot_id: str = Field(min_length=1)
    output: str = ""


class ActionError(BaseModel):
    type: Literal["error"] = "error"
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


ActionResult = Annotated[ReadFileResult | CoverageResult | ActionError, Field(discriminator="type")]


class WorkspaceAction(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    request: ActionRequest
    status: Literal["pending", "completed", "cancelled"] = "pending"
    result: ActionResult | None = None


class SubmitActionResult(BaseModel):
    result: ActionResult
