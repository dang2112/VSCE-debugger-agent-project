"""Lazy Sentence-BERT document search through the partner retrieval worker."""
from tools.documents import DocumentSearchArguments, search_documents


def semantic_search(workspace_path: str | None, arguments: DocumentSearchArguments, is_cancelled=None) -> dict:
    return search_documents(workspace_path, arguments, 'semantic', is_cancelled)
