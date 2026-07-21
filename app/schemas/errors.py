from enum import Enum

from pydantic import BaseModel, Field


class ErrorCode(str, Enum):
    FILE_NOT_FOUND = "file_not_found"
    PAPER_NOT_FOUND = "paper_not_found"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    PARSE_FAILED = "parse_failed"
    EXTRACTION_FAILED = "extraction_failed"
    EMBEDDING_FAILED = "embedding_failed"
    SCHEMA_VALIDATION_FAILED = "schema_validation_failed"
    EVIDENCE_BINDING_FAILED = "evidence_binding_failed"
    GRAPH_WRITE_FAILED = "graph_write_failed"
    KAG_QUERY_FAILED = "kag_query_failed"
    GRAPH_QUERY_FAILED = "graph_query_failed"
    TAXONOMY_NOT_CONFIGURED = "taxonomy_not_configured"
    TOPIC_UNRESOLVED = "topic_unresolved"
    INTERNAL_ERROR = "internal_error"


class SkillError(BaseModel):
    code: ErrorCode | str
    message: str
    detail: dict = Field(default_factory=dict)
