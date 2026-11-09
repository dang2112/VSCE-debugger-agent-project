"""Literal and BM25 searches over project documentation, never source files."""
from tools.documents import DocumentSearchArguments, search_documents


def exact_search(workspace_path: str | None, arguments: DocumentSearchArguments, is_cancelled=None) -> dict:
    return search_documents(workspace_path, arguments, 'exact', is_cancelled)


def lexical_search(workspace_path: str | None, arguments: DocumentSearchArguments, is_cancelled=None) -> dict:
    return search_documents(workspace_path, arguments, 'bm25', is_cancelled)
