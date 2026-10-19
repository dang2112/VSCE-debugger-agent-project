#this file is the HTTP request/response schemas
from enum import Enum
from pydantic import BaseModel, Field


class FailureType(str, Enum):
    RUNTIME_ERROR = "runtime_error"
    TEST_FAILURE = "test_failure"

class DebugMode(str, Enum):
    DIRECT = "direct"
    AGENT = "agent"

class DebugStage(str, Enum):
    CREATED = "created"
    COLLECTING_EVIDENCE = "collecting_evidence"
    FAULT_LOCALIZATION = "fault_localization"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    BUILDING_REPAIR_CONTEXT = "building_repair_context"
    GENERATING_PATCH = "generating_patch"
    VERIFYING_PATCH = "verifying_patch"
    COMPLETED = "completed"
    FAILED = "failed"

class SourceFile(BaseModel):
    path: str
    content: str


class DebugProblem(BaseModel):
    failure_type: FailureType

    error_log: str | None = None

    failing_tests: list[str] = Field(
        default_factory=list
    )


class DebugContext(BaseModel):
    files: list[SourceFile] = Field(
        default_factory=list
    )


class CreateDebugSessionRequest(BaseModel):
    mode: DebugMode = DebugMode.DIRECT

    problem: DebugProblem
    context: DebugContext


class CreateDebugSessionResponse(BaseModel):
    session_id: str
    status: DebugStage


class DebugSessionStatusResponse(BaseModel):
    session_id: str
    status: DebugStage

    patch_attempt: int = 0
    max_patch_attempts: int = 3


class RunDebugSessionResponse(BaseModel):
    session_id: str
    status: DebugStage


class DebugResultResponse(BaseModel):
    session_id: str
    status: DebugStage

    explanation: str | None = None
    patch: str | None = None
    verification_status: str | None = None