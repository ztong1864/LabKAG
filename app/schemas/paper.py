from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.extraction import PaperExtractionResult


class ExtractPaperRequest(BaseModel):
    file_id: str
    project_id: str | None = None
    extract_level: Literal["basic", "detailed"] = "basic"
    return_chunks: bool = False
    use_backup: bool = False


class IngestPaperRequest(BaseModel):
    project_id: str | None = None
    paper_extraction: PaperExtractionResult
    confirm: bool = False


class QueryLiteratureRequest(BaseModel):
    question: str
    project_id: str | None = None
    paper_id: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class SearchEvidenceRequest(BaseModel):
    query: str
    project_id: str | None = None
    paper_id: str | None = None
    entity_types: list[str] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=100)
