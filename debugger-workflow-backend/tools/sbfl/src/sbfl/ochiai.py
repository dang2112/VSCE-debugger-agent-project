from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class FunctionSpectrum:
    function_id: str
    failing_covered: int
    passing_covered: int
    total_failing: int

    @property
    def score(self) -> float:
        if self.total_failing == 0 or self.failing_covered == 0:
            return 0.0
        denominator = math.sqrt(
            self.total_failing * (self.failing_covered + self.passing_covered)
        )
        if denominator == 0:
            return 0.0
        return self.failing_covered / denominator


@dataclass(frozen=True, slots=True)
class SuspiciousnessResult:
    rank: int
    function_id: str
    score: float
    failing_covered: int
    passing_covered: int
    total_failing: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def rank_functions(test_records: Iterable[dict[str, object]]) -> list[SuspiciousnessResult]:
    records = [record for record in test_records
               if not record.get("excluded_from_ranking")
               and record.get("outcome") in {"passed", "failed"}]
    failing = [record for record in records if record.get("outcome") == "failed"]
    passing = [record for record in records if record.get("outcome") == "passed"]
    total_failing = len(failing)

    all_functions: set[str] = set()
    for record in records:
        all_functions.update(str(item) for item in record.get("covered_functions", []))

    spectra: list[FunctionSpectrum] = []
    for function_id in all_functions:
        nf = sum(
            function_id in set(str(item) for item in record.get("covered_functions", []))
            for record in failing
        )
        np = sum(
            function_id in set(str(item) for item in record.get("covered_functions", []))
            for record in passing
        )
        spectra.append(
            FunctionSpectrum(
                function_id=function_id,
                failing_covered=nf,
                passing_covered=np,
                total_failing=total_failing,
            )
        )

    spectra.sort(
        key=lambda item: (
            -item.score,
            -item.failing_covered,
            item.passing_covered,
            item.function_id,
        )
    )

    return [
        SuspiciousnessResult(
            rank=index,
            function_id=spectrum.function_id,
            score=spectrum.score,
            failing_covered=spectrum.failing_covered,
            passing_covered=spectrum.passing_covered,
            total_failing=spectrum.total_failing,
        )
        for index, spectrum in enumerate(spectra, start=1)
    ]
