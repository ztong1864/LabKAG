from app.schemas.taxonomy import ProjectTaxonomy, TaxonomyCategory
from app.services.taxonomy_service import get_taxonomy, set_taxonomy
from app.storage.taxonomy_store import taxonomy_store


class FakeQueryStore:
    def __init__(self, affected_count: int = 0):
        self.affected_count = affected_count
        self.calls = []

    def count_papers_with_tag_values(self, project_id, removals):
        self.calls.append((project_id, removals))
        return self.affected_count


def _never_call_query_store():
    raise AssertionError("query_store_factory should not have been called")


def test_first_time_bootstrap_applies_immediately():
    taxonomy = ProjectTaxonomy(
        project_id="ignored",
        categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron"])],
    )

    result = set_taxonomy(
        "proj_1", taxonomy, confirm=False, query_store_factory=_never_call_query_store
    )

    assert result["status"] == "success"
    assert result["applied"] is True
    stored = taxonomy_store.load_taxonomy("proj_1")
    assert stored["version"] == 1
    assert stored["source"] == "human_authored"
    assert stored["project_id"] == "proj_1"


def test_pure_addition_edit_applies_immediately_without_confirm():
    taxonomy_store.save_taxonomy(
        "proj_1",
        ProjectTaxonomy(
            project_id="proj_1",
            categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron"])],
            version=1,
        ).model_dump(mode="json"),
    )
    edited = ProjectTaxonomy(
        project_id="proj_1",
        categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron", "copper"])],
    )

    result = set_taxonomy(
        "proj_1", edited, confirm=False, query_store_factory=_never_call_query_store
    )

    assert result["status"] == "success"
    stored = taxonomy_store.load_taxonomy("proj_1")
    assert stored["version"] == 2
    assert stored["source"] == "edited"
    assert set(stored["categories"][0]["allowed_values"]) == {"iron", "copper"}


def test_breaking_removal_without_confirm_returns_needs_review_and_does_not_persist():
    taxonomy_store.save_taxonomy(
        "proj_1",
        ProjectTaxonomy(
            project_id="proj_1",
            categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron", "mercury"])],
            version=1,
        ).model_dump(mode="json"),
    )
    edited = ProjectTaxonomy(
        project_id="proj_1",
        categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron"])],
    )
    fake_store = FakeQueryStore(affected_count=3)

    result = set_taxonomy("proj_1", edited, confirm=False, query_store_factory=lambda: fake_store)

    assert result == {"status": "needs_review", "applied": False, "affected_papers_count": 3}
    assert fake_store.calls == [
        ("proj_1", [{"property": "tag_catalyst_type", "value": "mercury"}])
    ]
    stored = taxonomy_store.load_taxonomy("proj_1")
    assert stored["version"] == 1
    assert set(stored["categories"][0]["allowed_values"]) == {"iron", "mercury"}


def test_breaking_removal_with_confirm_persists_and_bumps_version():
    taxonomy_store.save_taxonomy(
        "proj_1",
        ProjectTaxonomy(
            project_id="proj_1",
            categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron", "mercury"])],
            version=1,
        ).model_dump(mode="json"),
    )
    edited = ProjectTaxonomy(
        project_id="proj_1",
        categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron"])],
    )

    result = set_taxonomy(
        "proj_1", edited, confirm=True, query_store_factory=_never_call_query_store
    )

    assert result["status"] == "success"
    assert result["applied"] is True
    stored = taxonomy_store.load_taxonomy("proj_1")
    assert stored["version"] == 2
    assert stored["categories"][0]["allowed_values"] == ["iron"]


def test_get_taxonomy_returns_none_when_missing():
    assert get_taxonomy("no_such_project") is None
