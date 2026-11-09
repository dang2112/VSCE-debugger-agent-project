from sbfl.ochiai import FunctionSpectrum, rank_functions


def test_ochiai_formula():
    spectrum = FunctionSpectrum(
        function_id="demo::faulty",
        failing_covered=2,
        passing_covered=3,
        total_failing=2,
    )
    assert spectrum.score == 2 / (10 ** 0.5)


def test_rank_functions_prefers_more_failure_specific_function():
    records = [
        {
            "outcome": "failed",
            "covered_functions": ["faulty", "common"],
        },
        {
            "outcome": "failed",
            "covered_functions": ["faulty", "common"],
        },
        {
            "outcome": "passed",
            "covered_functions": ["common"],
        },
        {
            "outcome": "passed",
            "covered_functions": ["common"],
        },
    ]

    ranking = rank_functions(records)
    assert ranking[0].function_id == "faulty"
    assert ranking[0].score == 1.0
    assert ranking[1].function_id == "common"
