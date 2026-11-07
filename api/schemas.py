#this file is the HTTP request/response schemas
from enum import Enum
from pydantic import BaseModel, Field
from orchestrator.preparation import PreparationConfig

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
    preparation: PreparationConfig = Field(default_factory=PreparationConfig)


class CreateDebugSessionResponse(BaseModel):
    session_id: str
    status: DebugStage


class DebugSessionStatusResponse(BaseModel):
    session_id: str
    status: DebugStage

    patch_attempt: int = 0
    max_patch_attempts: int = 3
    preparation_status: str = "pending"
    pending_actions: int = 0
    agent_turns: int = 0


class RunDebugSessionResponse(BaseModel):
    session_id: str
    status: DebugStage


class CancelDebugSessionResponse(BaseModel):
    session_id: str
    status: DebugStage


class DebugResultResponse(BaseModel):
    session_id: str
    status: DebugStage

    explanation: str | None = None
    patch: str | None = None
    verification_status: VerificationStatus | None = None
    error: str | None = None
