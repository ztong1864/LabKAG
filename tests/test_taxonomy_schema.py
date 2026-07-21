import pytest
from pydantic import ValidationError

from app.schemas.taxonomy import (
    MatchedPaper,
    MatchTopicRequest,
    ProjectTaxonomy,
    TaxonomyCategory,
    TopicConcept,
    TopicPlan,
)


def test_taxonomy_category_defaults():
    category = TaxonomyCategory(key="catalyst_type")

    assert category.allowed_values == []
    assert category.aliases == {}
    assert category.essential_by_default is False


def test_project_taxonomy_accepts_categories_and_defaults_version():
    taxonomy = ProjectTaxonomy(
        project_id="proj_123",
        categories=[
            TaxonomyCategory(
                key="catalyst_type",
                allowed_values=["iron", "copper"],
                aliases={"iron": ["Fe(NO3)3", "iron nitrate"]},
                essential_by_default=True,
            )
        ],
    )

    assert taxonomy.version == 1
    assert taxonomy.source == "human_authored"
    assert taxonomy.categories[0].aliases["iron"] == ["Fe(NO3)3", "iron nitrate"]


def test_topic_plan_accepts_concepts_and_unresolved():
    plan = TopicPlan(
        topic="Iron-catalyzed aerobic oxidation",
        project_id="proj_123",
        concepts=[
            TopicConcept(
                category="catalyst_type",
                value="iron",
                essential=True,
                confidence=0.9,
                reason="Topic explicitly names iron.",
            )
        ],
        unresolved=[{"surface": "APA", "reason": "ambiguous abbreviation"}],
        year_from=2021,
        year_to=2026,
    )

    assert plan.concepts[0].essential is True
    assert plan.unresolved[0]["surface"] == "APA"


def test_matched_paper_requires_tier():
    with pytest.raises(ValidationError):
        MatchedPaper(paper_id="paper_001")

    matched = MatchedPaper(paper_id="paper_001", tier="confirmed")
    assert matched.co_occurrence is False
    assert matched.embedding_score is None
    assert matched.reasons == []


def test_match_topic_request_defaults():
    plan = TopicPlan(topic="X", project_id="proj_123")
    request = MatchTopicRequest(project_id="proj_123", plan=plan)

    assert request.min_essential_signals == 2
    assert request.include_borderline is True
    assert request.limit is None


def test_match_topic_request_rejects_non_positive_min_essential_signals():
    plan = TopicPlan(topic="X", project_id="proj_123")
    with pytest.raises(ValidationError):
        MatchTopicRequest(project_id="proj_123", plan=plan, min_essential_signals=0)
