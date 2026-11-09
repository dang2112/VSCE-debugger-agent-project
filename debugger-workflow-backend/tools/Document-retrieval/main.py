# main.py

from exact_search import exact_search
from bm25_search import bm25_search
from semantic_bert import semantic_search
from adaptive_k import adaptive_k


DOCUMENT_PATH = (
    "documents/example.md"
)


def print_results(
    title: str,
    results: list[dict],
):
    print("\n")
    print("=" * 60)
    print(title)
    print("=" * 60)

    if not results:
        print("No results.")
        return

    for index, result in enumerate(
        results,
        start=1,
    ):
        print(
            f"\nResult #{index}"
        )

        print(
            f"Chunk: {result['chunk_id']}"
        )

        print(
            f"Method: {result['method']}"
        )

        print(
            f"Score: {result['score']:.4f}"
        )

        print(
            result["text"]
        )


def main():

    # -----------------------------------------
    # EXACT SEARCH
    # -----------------------------------------

    exact_results = exact_search(
        file_path=DOCUMENT_PATH,
        query="process_payment",
        top_k=5,
    )

    print_results(
        "EXACT SEARCH",
        exact_results,
    )

    # -----------------------------------------
    # BM25 SEARCH
    # -----------------------------------------

    bm25_results = bm25_search(
        file_path=DOCUMENT_PATH,
        query="payment balance failure",
        top_k=5,
    )

    print_results(
        "BM25 SEARCH",
        bm25_results,
    )

    # -----------------------------------------
    # SEMANTIC SEARCH
    # -----------------------------------------

    semantic_results = semantic_search(
        file_path=DOCUMENT_PATH,
        query=(
            "What happens when the customer "
            "does not have enough money?"
        ),
        top_k=5,
    )

    print_results(
        "SEMANTIC SEARCH",
        semantic_results,
    )

    # -----------------------------------------
    # ADAPTIVE-K
    # -----------------------------------------

    selected = adaptive_k(
        semantic_results
    )

    print_results(
        "ADAPTIVE-K",
        selected,
    )


if __name__ == "__main__":
    main()