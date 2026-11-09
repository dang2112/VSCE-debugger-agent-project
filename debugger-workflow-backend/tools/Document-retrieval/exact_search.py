# exact_search.py

from pathlib import Path


def load_markdown_chunks(file_path: str) -> list[str]:
    text = Path(file_path).read_text(
        encoding="utf-8"
    )

    chunks = []
    current_chunk = []

    for line in text.splitlines():
        # Start a new chunk when we encounter
        # a Markdown heading.
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


def exact_search(
    file_path: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Search for the exact query string inside
    a Markdown document.
    """

    query = query.strip()

    if not query:
        return []

    chunks = load_markdown_chunks(file_path)

    results = []

    for index, chunk in enumerate(chunks):
        count = chunk.lower().count(
            query.lower()
        )

        if count > 0:
            results.append(
                {
                    "chunk_id": index,
                    "text": chunk,
                    "score": float(count),
                    "method": "exact",
                }
            )

    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )

    return results[:top_k]