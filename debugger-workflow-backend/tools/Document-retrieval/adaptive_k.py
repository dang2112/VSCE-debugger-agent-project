# adaptive_k.py


def adaptive_k(
    results: list[dict],
    max_k: int = 5,
    drop_threshold: float = 0.30,
) -> list[dict]:
    """
    Reduce the top results based on
    relative score drop.

    Example:

    0.91
    0.88
    0.82
    0.40
    0.38

    Large drop between 0.82 and 0.40
    => keep first 3.
    """

    if not results:
        return []

    results = results[:max_k]

    if len(results) == 1:
        return results

    selected = [
        results[0]
    ]

    for index in range(1, len(results)):
        previous_score = results[index - 1]["score"]
        current_score = results[index]["score"]

        if previous_score == 0:
            break

        relative_drop = (
            previous_score - current_score
        ) / abs(previous_score)

        if relative_drop >= drop_threshold:
            break

        selected.append(
            results[index]
        )

    return selected