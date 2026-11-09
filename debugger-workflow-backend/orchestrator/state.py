from enum import Enum
from uuid import uuid4
from pydantic import BaseModel, Field
from orchestrator.snapshots import SourceFile
from orchestrator.actions import WorkspaceAction
from orchestrator.preparation import PreparationConfig
from orchestrator.repair_config import RepairConfig
from typing import Literal


# ============================================================
# Pipeline state
# ============================================================

class DebugStage(str, Enum):
    CREATED = "created"
    COLLECTING_EVIDENCE = "collecting_evidence"
    WAITING_FOR_CONTEXT = "waiting_for_context"
    FAULT_LOCALIZATION = "fault_localization"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    REVIEWING_ANALYSIS = "reviewing_analysis"
    BUILDING_REPAIR_CONTEXT = "building_repair_context"
    GENERATING_PATCH = "generating_patch"
    VERIFYING_PATCH = "verifying_patch"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FailureType(str, Enum):
    RUNTIME_ERROR = "runtime_error"
    TEST_FAILURE = "test_failure"


class DebugMode(str, Enum):
    DIRECT = "direct"
    TWO_THINKING_TIMES = "two-thinking-times"
    AGENT = "agent"


# ============================================================
# Initial debugging problem
# ============================================================

class DebugProblem(BaseModel):
    failure_type: FailureType
    user_message: str = ""
    error_log: str | None = None
    failing_tests: list[str] = Field(default_factory=list)


class DebugContext(BaseModel):
    workspace_path: str | None = None
    workspace_id: str | None = None
    workspace_uri: str | None = None
    active_file: SourceFile | None = None
    files: list[SourceFile] = Field(default_factory=list)


# ============================================================
# Evidence
# ============================================================
#everything discovered during debugging can become an EvidenceItem.

class EvidenceType(str, Enum):
    DOCUMENT = "document"
    PROJECT_STRUCTURE = "project_structure"
    SOURCE_CODE = "source_code"
    TRACEBACK = "traceback"
    TEST_OUTPUT = "test_output"
    SBFL_RESULT = "sbfl_result"
    LEXICAL_RESULT = "lexical_result"
    SEMANTIC_RESULT = "semantic_result"
    RAG_RESULT = "rag_result"
    OTHER = "other"


class EvidenceItem(BaseModel):
    id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    type: EvidenceType
    source: str

    path: str | None = None
    symbol: str | None = None

    content: str

    score: float | None = None

    metadata: dict = Field(
        default_factory=dict
    )

# ============================================================
# Fault localization
# ============================================================

class FaultCandidate(BaseModel): #SBFL ranking
    path: str

    function: str | None = None

    suspiciousness: float

    line_start: int | None = None
    line_end: int | None = None

    metadata: dict = Field(
        default_factory=dict
    )


class FaultLocalizationResult(BaseModel): #the rest of the system can reason over this
    candidates: list[FaultCandidate] = Field(
        default_factory=list
    )

    evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

# ============================================================
# Root Cause Analysis
# ============================================================

class RootCauseHypothesis(BaseModel): #this gives more structure to the response from the LLM, so it doesnt just output a stream of ideas
    summary: str

    root_cause_file: str | None = None
    root_cause_function: str | None = None

    supporting_evidence_ids: list[str] = Field(
        default_factory=list
    )

    rejected_evidence_ids: list[str] = Field(
        default_factory=list
    )

    confidence: float | None = Field(default=None, ge=0, le=1)


class RootCauseAnalysisResult(BaseModel):
    hypothesis: RootCauseHypothesis

    inspected_evidence_ids: list[str] = Field(
        default_factory=list
    )

    notes: str | None = None

# ============================================================
# Repair context
# ============================================================

class RepairContext(BaseModel):
    hypothesis: RootCauseHypothesis

    selected_evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    relevant_files: list[SourceFile] = Field(
        default_factory=list
    )

    notes: str | None = None
    problem: DebugProblem | None = None
    editable_paths: list[str] = Field(default_factory=list)
    source_hashes: dict[str, str] = Field(default_factory=dict)

# ============================================================
# Patch generation
# ============================================================

class GeneratedPatch(BaseModel):
    diff: str = Field(max_length=200000)
    explanation: str | None = None
    base_hashes: dict[str, str] = Field(default_factory=dict)


class VerificationStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNVERIFIED = "unverified"


class TestStageStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"
    ERROR = "error"
    TIMED_OUT = "timed_out"

# ============================================================
# Verification
# ============================================================

class VerificationStageResult(BaseModel):
    status: TestStageStatus

    command: str | None = None
    output: str | None = None
    exit_code: int | None = None
    reason: str | None = None
    outcomes: dict[str, str] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    failing_tests: VerificationStageResult

    regression_tests: VerificationStageResult

    full_suite: VerificationStageResult

    overall_status: VerificationStatus
    baseline: VerificationStageResult | None = None
    patch_applied: bool = False
    error: str | None = None
    snapshot_id: str | None = None


class PatchAttempt(BaseModel):
    attempt_number: int

    patch: GeneratedPatch

    verification: VerificationResult | None = None
    generation_error: str | None = None

# ============================================================
# Complete debugging session state
# ============================================================

class DebugSession(BaseModel):
    session_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    mode: DebugMode = DebugMode.DIRECT

    stage: DebugStage = DebugStage.CREATED
    problem: DebugProblem
    context: DebugContext

    evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    fault_localization: FaultLocalizationResult | None = None
    root_cause_analysis: RootCauseAnalysisResult | None = None
    repair_context: RepairContext | None = None
    patch_attempts: list[PatchAttempt] = Field(
        default_factory=list
    )

    final_status: VerificationStatus | None = None
    final_explanation: str | None = None
    debug_error: str | None = None #where in the pipeline did we fail? e.g Fault Localization failed because abc etc.

    workspace_actions: list[WorkspaceAction] = Field(default_factory=list)
    resume_stage: DebugStage | None = None
    agent_history: list[dict] = Field(default_factory=list)
    agent_pending_results: dict[str, dict] = Field(default_factory=dict)
    agent_pending_actions: dict[str, str] = Field(default_factory=dict)
    agent_turns: int = 0
    agent_source_chars: int = 0
    max_agent_turns: int = Field(default=12, ge=1, le=50)
    sbfl_run_id: str | None = None
    project_overview: dict | None = None
    document_searches: dict[str, dict] = Field(default_factory=dict)
    document_context_chars: int = 0
    preparation: PreparationConfig = Field(default_factory=PreparationConfig)
    preparation_status: Literal["pending", "localized", "ready", "fallback", "disabled"] = "pending"
    preparation_summary: dict = Field(default_factory=dict)
    preload_paths: list[str] = Field(default_factory=list)
    preload_actions: dict[str, str] = Field(default_factory=dict)

    max_patch_attempts: int = 3
    repair: RepairConfig = Field(default_factory=RepairConfig)
    analysis_explanation: str | None = None
    repair_file_actions: dict[str, str] = Field(default_factory=dict)
    verification_snapshot: str | None = None
    baseline_verification: VerificationStageResult | None = None
    reproduced_tests: list[str] = Field(default_factory=list)
