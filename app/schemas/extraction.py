from pydantic import BaseModel, Field

from app.schemas.evidence import Evidence


class PaperMetadata(BaseModel):
    paper_id: str | None = None
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: str = ""
    doi: str = ""
    journal: str = ""
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    document_id: str | None = None


class EvidenceBoundItem(BaseModel):
    evidence: list[Evidence] = Field(default_factory=list)
    needs_review: bool = False
    inferred: bool = False
    tags: dict[str, str] = Field(default_factory=dict)


class ExtractedMethod(EvidenceBoundItem):
    method_id: str = ""
    name: str = ""
    description: str = ""
    method_type: str = ""


class ExtractedMaterial(EvidenceBoundItem):
    material_id: str = ""
    name: str = ""
    type: str = ""
    description: str = ""


class ExtractedCondition(EvidenceBoundItem):
    condition_id: str = ""
    name: str = ""
    value: str = ""
    unit: str = ""
    normalized_value: str = ""
    normalized_unit: str = ""
    description: str = ""


class ExtractedMetric(EvidenceBoundItem):
    metric_id: str = ""
    name: str = ""
    value: str = ""
    unit: str = ""
    description: str = ""


class ExtractedResult(EvidenceBoundItem):
    result_id: str = ""
    description: str = ""
    value: str = ""
    unit: str = ""
    result_type: str = ""


class ExtractedConclusion(EvidenceBoundItem):
    conclusion_id: str = ""
    description: str = ""
    scope: str = ""


class PaperExtractionResult(BaseModel):
    document_id: str
    paper: PaperMetadata = Field(default_factory=PaperMetadata)
    methods: list[ExtractedMethod] = Field(default_factory=list)
    materials: list[ExtractedMaterial] = Field(default_factory=list)
    conditions: list[ExtractedCondition] = Field(default_factory=list)
    metrics: list[ExtractedMetric] = Field(default_factory=list)
    results: list[ExtractedResult] = Field(default_factory=list)
    conclusions: list[ExtractedConclusion] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    extractor_version: str = "v0.1"
    created_at: str = ""
    paper_embedding: list[float] | None = None
    taxonomy_version: int | None = None
