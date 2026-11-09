# semantic_bert.py
from pathlib import Path

from sentence_transformers import SentenceTransformer


MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

model = SentenceTransformer(
    MODEL_NAME
)


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


def semantic_search(
    file_path: str,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """
    Perform semantic search using Sentence-BERT
    over one Markdown file.
    """

    query = query.strip()

    if not query:
        return []

    chunks = load_markdown_chunks(
        file_path
    )

    document_embeddings = (
        model.encode_document(
            chunks,
            normalize_embeddings=True,  
            convert_to_tensor=True,
        )
    )

    query_embedding = (
        model.encode_query(
            [query],
            normalize_embeddings=True,
            convert_to_tensor=True,
        )
    )

    similarities = model.similarity(
        query_embedding,
        document_embeddings,
    )[0]

    scores = similarities.cpu().tolist()

    results = []

    for index, score in enumerate(scores):
        results.append(
            {
                "chunk_id": index,
                "text": chunks[index],
                "score": float(score),
                "method": "semantic",
            }
        )

    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )

    return results[:top_k]