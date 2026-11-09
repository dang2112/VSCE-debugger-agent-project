#this file is the HTTP request/response schemas
from enum import Enum
from pydantic import BaseModel, Field, model_validator
from orchestrator.preparation import PreparationConfig
from orchestrator.repair_config import RepairConfig

from orchestrator.state import (
    DebugContext,
    DebugMode,
    DebugProblem,
    DebugStage,
    VerificationStatus,
    VerificationResult,
    RootCauseAnalysisResult,
)


class CreateDebugSessionRequest(BaseModel):
    mode: DebugMode = DebugMode.DIRECT

    problem: DebugProblem
    context: DebugContext
    preparation: PreparationConfig = Field(default_factory=PreparationConfig)
    repair: RepairConfig = Field(default_factory=RepairConfig)

    @model_validator(mode='after')
    def repair_requires_agent(self):
        if self.repair.enabled and self.mode != DebugMode.AGENT:
            raise ValueError('Repair requires mode=agent')
        return self


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
    base_hashes: dict[str, str] = Field(default_factory=dict)
    verification: VerificationResult | None = None
    diagnosis: RootCauseAnalysisResult | None = None
    baseline: dict | None = None
