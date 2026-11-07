"""Versioned editor or disk content captured by the extension."""
from pydantic import BaseModel, Field


class SourceFile(BaseModel):
    path: str
    content: str
    uri: str | None = None
    document_version: int | None = Field(default=None, ge=0)
    content_hash: str | None = None
    is_dirty: bool = False
