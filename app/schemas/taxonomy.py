from typing import Literal

from pydantic import BaseModel, Field


class TaxonomyCategory(BaseModel):
    key: str
    description: str = ""
    allowed_values: list[str] = Field(default_factory=list)
    aliases: dict[str, list[str]] = Field(default_factory=dict)
    essential_by_default: bool = False


class ProjectTaxonomy(BaseModel):
    project_id: str
    categories: list[TaxonomyCategory] = Field(default_factory=list)
    version: int = 1
    source: Literal["human_authored", "llm_bootstrapped", "edited"] = "human_authored"
    updated_at: str = ""


class TopicConcept(BaseModel):
    category: str
    value: str
    essential: bool = False
    confidence: float = 0.0
    reason: str = ""


class TopicPlan(BaseModel):
    topic: str
    project_id: str
    concepts: list[TopicConcept] = Field(default_factory=list)
    unresolved: list[dict] = Field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None


class MatchedPaper(BaseModel):
    paper_id: str
    title: str = ""
    year: int | None = None
    tier: Literal["confirmed", "borderline"]
    matched_concepts: list[dict] = Field(default_factory=list)
    co_occurrence: bool = False
    embedding_score: float | None = None
    reasons: list[str] = Field(default_factory=list)


class MatchTopicRequest(BaseModel):
    project_id: str
    plan: TopicPlan
    min_essential_signals: int = Field(default=2, ge=1)
    include_borderline: bool = True
    limit: int | None = None
