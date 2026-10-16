from typing import Protocol


class FaultLocalizationService(Protocol):

    def localize(
        self,
        request: FaultLocalizationRequest
    ) -> FaultLocalizationResult:
        ...


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


class VerificationService(Protocol):

    def verify(
        self,
        request: VerificationRequest
    ) -> VerificationResult:
        ...