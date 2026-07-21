from collections.abc import Callable
from typing import Any

from app.schemas.taxonomy import ProjectTaxonomy
from app.storage.taxonomy_store import taxonomy_store
from app.utils.time import utc_now_iso


def get_taxonomy(project_id: str) -> dict[str, Any] | None:
    return taxonomy_store.load_taxonomy(project_id)


def _removed_or_renamed_values(
    existing: ProjectTaxonomy, incoming: ProjectTaxonomy
) -> list[dict[str, str]]:
    """Values allowed under `existing` that are no longer allowed under
    `incoming` (whether their category was edited or dropped entirely),
    shaped for Neo4jQueryStore.count_papers_with_tag_values."""
    incoming_values_by_category = {
        category.key: set(category.allowed_values) for category in incoming.categories
    }
    removals: list[dict[str, str]] = []
    for category in existing.categories:
        incoming_values = incoming_values_by_category.get(category.key, set())
        for value in category.allowed_values:
            if value not in incoming_values:
                removals.append({"property": f"tag_{category.key}", "value": value})
    return removals


def set_taxonomy(
    project_id: str,
    incoming: ProjectTaxonomy,
    confirm: bool,
    query_store_factory: Callable[[], Any],
) -> dict[str, Any]:
    """`query_store_factory` is only invoked when a breaking edit actually
    needs checking, so a first-time taxonomy bootstrap (no existing taxonomy,
    nothing to diff) never requires Neo4j to be configured."""
    existing_payload = taxonomy_store.load_taxonomy(project_id)
    existing = ProjectTaxonomy.model_validate(existing_payload) if existing_payload else None

    if existing is not None:
        removals = _removed_or_renamed_values(existing, incoming)
        if removals and not confirm:
            affected_papers_count = query_store_factory().count_papers_with_tag_values(
                project_id, removals
            )
            return {
                "status": "needs_review",
                "applied": False,
                "affected_papers_count": affected_papers_count,
            }
        incoming.version = existing.version + 1
        incoming.source = "edited"
    else:
        incoming.version = 1

    incoming.project_id = project_id
    incoming.updated_at = utc_now_iso()
    taxonomy_store.save_taxonomy(project_id, incoming.model_dump(mode="json"))
    return {
        "status": "success",
        "applied": True,
        "taxonomy": incoming.model_dump(mode="json"),
    }
