import pytest

from app.adapters.neo4j_query_store import PaperEntityRow
from app.schemas.taxonomy import ProjectTaxonomy, TaxonomyCategory, TopicConcept, TopicPlan
from app.services.topic_matcher import TopicPlanError, match_topic, score_paper, verify_plan

CONCEPTS = [
    TopicConcept(category="catalyst_type", value="iron", essential=True),
    TopicConcept(category="substrate_class", value="alcohol", essential=False),
]


def _entity(entity_id, entity_type, properties, evidence_ids=()):
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "properties": properties,
        "evidence_ids": list(evidence_ids),
    }


# ---- score_paper: the corroboration-boundary suite ----


def test_score_paper_returns_none_when_no_matches():
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Unrelated"},
        entities=[_entity("m1", "Material", {"tag_catalyst_type": "copper"})],
    )

    assert score_paper(CONCEPTS, row, min_essential_signals=2) is None


def test_score_paper_borderline_when_only_supporting_concept_matched():
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Alcohol paper"},
        entities=[_entity("m1", "Material", {"tag_substrate_class": "alcohol"}, ["ev_1"])],
    )

    result = score_paper(CONCEPTS, row, min_essential_signals=2)

    assert result is not None
    assert result.tier == "borderline"


def test_score_paper_confirmed_via_two_distinct_essential_categories():
    concepts = [
        TopicConcept(category="catalyst_type", value="iron", essential=True),
        TopicConcept(category="reaction_type", value="oxidation", essential=True),
    ]
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Iron oxidation paper"},
        entities=[
            _entity("m1", "Material", {"tag_catalyst_type": "iron"}, ["ev_1"]),
            _entity("c1", "Condition", {"tag_reaction_type": "oxidation"}, ["ev_2"]),
        ],
    )

    result = score_paper(concepts, row, min_essential_signals=2)

    assert result is not None
    assert result.tier == "confirmed"
    assert result.co_occurrence is False


def test_score_paper_confirmed_via_central_match_and_co_occurrence():
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Iron alcohol paper"},
        entities=[
            _entity("r1", "Result", {"tag_catalyst_type": "iron"}, ["ev_1"]),
            _entity("m1", "Material", {"tag_substrate_class": "alcohol"}, ["ev_1"]),
        ],
    )

    result = score_paper(CONCEPTS, row, min_essential_signals=2)

    assert result is not None
    assert result.tier == "confirmed"
    assert result.co_occurrence is True


def test_score_paper_borderline_when_essential_match_not_on_central_entity():
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Iron paper"},
        entities=[_entity("meth1", "Method", {"tag_catalyst_type": "iron"}, ["ev_1"])],
    )

    result = score_paper(CONCEPTS, row, min_essential_signals=2)

    assert result is not None
    assert result.tier == "borderline"


def test_score_paper_borderline_when_central_match_has_no_co_occurrence():
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Iron paper"},
        entities=[_entity("r1", "Result", {"tag_catalyst_type": "iron"}, ["ev_1"])],
    )

    result = score_paper(CONCEPTS, row, min_essential_signals=2)

    assert result is not None
    assert result.tier == "borderline"


def test_score_paper_confirmed_at_min_essential_signals_one():
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Iron paper"},
        entities=[_entity("meth1", "Method", {"tag_catalyst_type": "iron"}, ["ev_1"])],
    )

    result = score_paper(CONCEPTS, row, min_essential_signals=1)

    assert result is not None
    assert result.tier == "confirmed"


def test_score_paper_dedupes_essential_count_by_category():
    concepts = [
        TopicConcept(category="catalyst_type", value="iron", essential=True),
        TopicConcept(category="catalyst_type", value="copper", essential=True),
    ]
    row = PaperEntityRow(
        paper_id="paper_001",
        paper_properties={"title": "Iron paper"},
        entities=[_entity("m1", "Material", {"tag_catalyst_type": "iron"})],
    )

    result = score_paper(concepts, row, min_essential_signals=2)

    assert result is not None
    assert result.tier == "borderline"


# ---- match_topic: embedding can never promote on its own ----


class FakeEmbeddingClient:
    def __init__(self, vector):
        self.vector = vector

    def embed_texts(self, texts):
        return [self.vector]


class FakeQueryStore:
    def __init__(self, rows):
        self.rows = rows

    def fetch_entities_for_topic_matching(self, project_id):
        return self.rows


def test_match_topic_never_promotes_paper_via_embedding_alone():
    rows = [
        PaperEntityRow(
            paper_id="paper_001",
            paper_properties={"title": "Unrelated", "paper_embedding": [1.0, 0.0]},
            entities=[],
        )
    ]
    plan = TopicPlan(topic="iron catalysis", project_id="proj_1", concepts=CONCEPTS)

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=True,
        limit=None,
        query_store=FakeQueryStore(rows),
        embedding_client=FakeEmbeddingClient([1.0, 0.0]),
    )

    assert result["confirmed"] == []
    assert result["borderline"] == []
    assert result["summary"]["excluded_count"] == 1


# ---- match_topic: orchestration ----


def _confirmed_row(paper_id: str) -> PaperEntityRow:
    return PaperEntityRow(
        paper_id=paper_id,
        paper_properties={"title": paper_id},
        entities=[
            _entity(f"m_{paper_id}", "Material", {"tag_catalyst_type": "iron"}),
            _entity(f"c_{paper_id}", "Condition", {"tag_reaction_type": "oxidation"}),
        ],
    )


def _borderline_row(paper_id: str) -> PaperEntityRow:
    return PaperEntityRow(
        paper_id=paper_id,
        paper_properties={"title": paper_id},
        entities=[_entity(f"bm_{paper_id}", "Material", {"tag_substrate_class": "alcohol"})],
    )


_MULTI_TIER_CONCEPTS = [
    TopicConcept(category="catalyst_type", value="iron", essential=True),
    TopicConcept(category="reaction_type", value="oxidation", essential=True),
    TopicConcept(category="substrate_class", value="alcohol", essential=False),
]


def test_match_topic_applies_limit_per_tier_independently():
    rows = [_confirmed_row(f"confirmed_{i}") for i in range(3)] + [
        _borderline_row(f"borderline_{i}") for i in range(3)
    ]
    plan = TopicPlan(topic="iron oxidation", project_id="proj_1", concepts=_MULTI_TIER_CONCEPTS)

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=True,
        limit=2,
        query_store=FakeQueryStore(rows),
        embedding_client=None,
    )

    assert len(result["confirmed"]) == 2
    assert len(result["borderline"]) == 2
    assert result["summary"]["candidates_scanned"] == 6
    assert result["summary"]["confirmed_count"] == 2
    assert result["summary"]["borderline_count"] == 2


def test_match_topic_excludes_borderline_when_not_requested():
    rows = [_confirmed_row("confirmed_0"), _borderline_row("borderline_0")]
    plan = TopicPlan(topic="iron oxidation", project_id="proj_1", concepts=_MULTI_TIER_CONCEPTS)

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=False,
        limit=None,
        query_store=FakeQueryStore(rows),
        embedding_client=None,
    )

    assert len(result["confirmed"]) == 1
    assert result["borderline"] == []
    assert result["summary"]["borderline_count"] == 0


def test_match_topic_summary_counts_excluded_papers():
    rows = [
        _confirmed_row("confirmed_0"),
        PaperEntityRow(paper_id="unrelated", paper_properties={"title": "Unrelated"}, entities=[]),
    ]
    plan = TopicPlan(topic="iron oxidation", project_id="proj_1", concepts=_MULTI_TIER_CONCEPTS)

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=True,
        limit=None,
        query_store=FakeQueryStore(rows),
        embedding_client=None,
    )

    assert result["summary"] == {
        "candidates_scanned": 2,
        "confirmed_count": 1,
        "borderline_count": 0,
        "excluded_count": 1,
    }


def test_match_topic_excludes_paper_outside_declared_year_range():
    rows = [
        _confirmed_row("in_range"),
        _confirmed_row("too_old"),
    ]
    rows[0].paper_properties["year"] = "2024"
    rows[1].paper_properties["year"] = "2010"
    plan = TopicPlan(
        topic="iron oxidation",
        project_id="proj_1",
        concepts=_MULTI_TIER_CONCEPTS,
        year_from=2024,
        year_to=2025,
    )

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=True,
        limit=None,
        query_store=FakeQueryStore(rows),
        embedding_client=None,
    )

    assert [paper.paper_id for paper in result["confirmed"]] == ["in_range"]
    assert result["confirmed"][0].year == 2024
    assert result["summary"]["excluded_count"] == 1


def test_match_topic_excludes_paper_with_missing_year_when_range_declared():
    rows = [_confirmed_row("no_year")]
    plan = TopicPlan(
        topic="iron oxidation",
        project_id="proj_1",
        concepts=_MULTI_TIER_CONCEPTS,
        year_from=2024,
        year_to=2025,
    )

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=True,
        limit=None,
        query_store=FakeQueryStore(rows),
        embedding_client=None,
    )

    assert result["confirmed"] == []
    assert result["summary"]["excluded_count"] == 1


def test_match_topic_applies_no_year_filter_when_plan_leaves_it_unset():
    rows = [_confirmed_row("no_year")]
    plan = TopicPlan(topic="iron oxidation", project_id="proj_1", concepts=_MULTI_TIER_CONCEPTS)

    result = match_topic(
        "proj_1",
        plan,
        min_essential_signals=2,
        include_borderline=True,
        limit=None,
        query_store=FakeQueryStore(rows),
        embedding_client=None,
    )

    assert [paper.paper_id for paper in result["confirmed"]] == ["no_year"]


# ---- verify_plan ----


def _taxonomy() -> ProjectTaxonomy:
    return ProjectTaxonomy(
        project_id="proj_1",
        categories=[
            TaxonomyCategory(
                key="catalyst_type",
                allowed_values=["iron", "copper"],
                aliases={"iron": ["Fe(NO3)3"]},
            )
        ],
    )


def test_verify_plan_drops_unknown_category_and_value():
    plan = TopicPlan(
        topic="iron catalysis",
        project_id="proj_1",
        concepts=[
            TopicConcept(category="catalyst_type", value="iron", essential=True),
            TopicConcept(category="unknown_category", value="x", essential=True),
            TopicConcept(category="catalyst_type", value="mercury", essential=True),
        ],
    )

    verified = verify_plan(plan, _taxonomy(), current_year=2026)

    assert len(verified.concepts) == 1
    assert verified.concepts[0].value == "iron"


def test_verify_plan_resolves_alias_to_canonical_value():
    plan = TopicPlan(
        topic="iron catalysis",
        project_id="proj_1",
        concepts=[TopicConcept(category="catalyst_type", value="Fe(NO3)3", essential=True)],
    )

    verified = verify_plan(plan, _taxonomy(), current_year=2026)

    assert verified.concepts[0].value == "iron"


def test_verify_plan_rejects_when_zero_essential_concepts_remain():
    plan = TopicPlan(
        topic="mercury catalysis",
        project_id="proj_1",
        concepts=[TopicConcept(category="catalyst_type", value="mercury", essential=True)],
    )

    with pytest.raises(TopicPlanError):
        verify_plan(plan, _taxonomy(), current_year=2026)


def test_verify_plan_accepts_matching_year_filter():
    plan = TopicPlan(
        topic="iron catalysis in the past 5 years",
        project_id="proj_1",
        concepts=[TopicConcept(category="catalyst_type", value="iron", essential=True)],
        year_from=2022,
        year_to=2026,
    )

    verified = verify_plan(plan, _taxonomy(), current_year=2026)

    assert (verified.year_from, verified.year_to) == (2022, 2026)


def test_verify_plan_rejects_mismatched_year_filter():
    plan = TopicPlan(
        topic="iron catalysis in the past 5 years",
        project_id="proj_1",
        concepts=[TopicConcept(category="catalyst_type", value="iron", essential=True)],
        year_from=2020,
        year_to=2024,
    )

    with pytest.raises(TopicPlanError):
        verify_plan(plan, _taxonomy(), current_year=2026)
