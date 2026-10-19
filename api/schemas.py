#this file is the HTTP request/response schemas
from enum import Enum
from pydantic import BaseModel, Field

from orchestrator.state import (
    DebugContext,
    DebugMode,
    DebugProblem,
    DebugStage,
    VerificationStatus,
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
    verification_status: VerificationStatus | None = None