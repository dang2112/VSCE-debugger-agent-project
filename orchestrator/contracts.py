from typing import Protocol
from pydantic import BaseModel, Field

from orchestrator.state import (
    DebugProblem,
    EvidenceItem,
    FaultLocalizationResult,
    GeneratedPatch,
    PatchAttempt,
    RepairContext,
    RootCauseAnalysisResult,
    RootCauseHypothesis,
    SourceFile,
    VerificationResult,
)

class FaultLocalizationRequest(BaseModel):
    workspace_path: str

    failing_tests: list[str] = Field(
        default_factory=list
    )


class FaultLocalizationService(Protocol):

    def localize(
        self,
        request: FaultLocalizationRequest,
    ) -> FaultLocalizationResult:
        ...

class RetrievalQuery(BaseModel):
    query: str

    top_k: int = 10

    workspace_path: str | None = None

class RetrievalResult(BaseModel):
    evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

class LexicalSearchService(Protocol):

    def search(
        self,
        request: RetrievalQuery
    ) -> list[RetrievalResult]:
        ...


class SemanticSearchService(Protocol):

    def search(
        self,
        request: RetrievalQuery
    ) -> list[RetrievalResult]:
        ...

class RagService(Protocol):

    def search(
        self,
        request: RetrievalQuery,
    ) -> RetrievalResult:
        ...

class ReadFileRequest(BaseModel):
    path: str


class FileSystemService(Protocol):

    def read_file(
        self,
        request: ReadFileRequest,
    ) -> SourceFile:
        ...

class RootCauseAnalysisRequest(BaseModel):
    problem: DebugProblem

    evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    fault_localization: FaultLocalizationResult | None = None

class RootCauseAnalysisService(Protocol):

    def analyze(
        self,
        request: RootCauseAnalysisRequest,
    ) -> RootCauseAnalysisResult:
        ...

class RepairContextRequest(BaseModel):
    hypothesis: RootCauseHypothesis

    available_evidence: list[EvidenceItem] = Field(
        default_factory=list
    )

    available_files: list[SourceFile] = Field(
        default_factory=list
    )


class RepairContextService(Protocol):

    def build(
        self,
        request: RepairContextRequest,
    ) -> RepairContext:
        ...

class PatchGenerationRequest(BaseModel):
    repair_context: RepairContext

    previous_attempts: list[PatchAttempt] = Field(
        default_factory=list
    )


class PatchGenerationService(Protocol):

    def generate(
        self,
        request: PatchGenerationRequest,
    ) -> GeneratedPatch:
        ...

class VerificationRequest(BaseModel):
    workspace_path: str

    patch: GeneratedPatch

    failing_tests: list[str] = Field(
        default_factory=list
    )


class VerificationService(Protocol):

    def verify(
        self,
        request: VerificationRequest,
    ) -> VerificationResult:
        ...