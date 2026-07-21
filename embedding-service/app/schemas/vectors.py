from typing import Optional

from pydantic import BaseModel, Field


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)


class IndexRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    document_id: Optional[str] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    sections: Optional[list[str]] = None
    document_date: Optional[str] = None
    document_type: Optional[str] = None
    uploaded_at: Optional[str] = None
    scope_key: str = "global"
    owner_username: Optional[str] = None
    knowledge_base: str = "global"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=30)
    scope_keys: list[str] = Field(default_factory=lambda: ["global"])
