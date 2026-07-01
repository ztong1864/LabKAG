from pydantic import BaseModel


class Evidence(BaseModel):
    evidence_id: str
    document_id: str
    chunk_id: str
    page: int
    section_title: str | None = None
    source_text: str
    offset_start: int | None = None
    offset_end: int | None = None
    paper_id: str | None = None
    embedding: list[float] | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
