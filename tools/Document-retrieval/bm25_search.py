# bm25_search.py
import re
from pathlib import Path

from rank_bm25 import BM25Okapi


def load_markdown_chunks(file_path: str) -> list[str]:
    text = Path(file_path).read_text(
        encoding="utf-8"
    )

    chunks = []
    current_chunk = []

    for line in text.splitlines():
        if line.startswith("#") and current_chunk:
            chunks.append("\n".join(current_chunk).strip())
            current_chunk = []

        current_chunk.append(line)

    if current_chunk:
        chunks.append("\n".join(current_chunk).strip())

    return [
        chunk
        for chunk in chunks
        if chunk.strip()
    ]


def tokenize(text: str) -> list[str]:
    return re.findall(
        r"[A-Za-z0-9_./:-]+",
        text.lower(),
    )


def bm25_search(
    file_path: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Perform BM25 lexical search over
    chunks from one Markdown file.
    """

    query = query.strip()

    if not query:
        return []

    chunks = load_markdown_chunks(
        file_path
    )

    tokenized_chunks = [
        tokenize(chunk)
        for chunk in chunks
    ]

    bm25 = BM25Okapi(
        tokenized_chunks
    )

    query_tokens = tokenize(query)

    scores = bm25.get_scores(
        query_tokens
    )

    results = []

    for index, score in enumerate(scores):
        score = float(score)

        if score <= 0:
            continue

        results.append(
            {
                "chunk_id": index,
                "text": chunks[index],
                "score": score,
                "method": "bm25",
            }
        )

    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )

    return results[:top_k]