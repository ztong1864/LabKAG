from pathlib import Path

from app.schemas.extraction import EvidenceBoundItem, PaperExtractionResult
from app.schemas.taxonomy import ProjectTaxonomy
from app.services.paper_extractor import ChatJSONClient


def _load_tagging_prompt() -> str:
    prompt_path = Path("app/prompts/entity_tagging.md")
    if prompt_path.exists() and prompt_path.read_text(encoding="utf-8").strip():
        return prompt_path.read_text(encoding="utf-8")
    return (
        'Assign controlled-vocabulary tags to already-extracted entities. Return strict '
        'JSON: {"tags": {"<entity_id>": {"<category>": "<value>"}}}. Only use category '
        "keys and values from the taxonomy provided. Omit an entity or category entirely "
        "if no confident tag applies."
    )


def _taxonomy_prompt(taxonomy: ProjectTaxonomy) -> str:
    lines = ["Taxonomy categories and allowed values:"]
    for category in taxonomy.categories:
        header = f"\n{category.key}"
        if category.description:
            header += f": {category.description}"
        lines.append(header)
        for value in category.allowed_values:
            aliases = category.aliases.get(value) or []
            alias_text = f" (aliases: {', '.join(aliases)})" if aliases else ""
            lines.append(f"  - {value}{alias_text}")
    return "\n".join(lines)


def _entity_by_id(extraction: PaperExtractionResult) -> dict[str, EvidenceBoundItem]:
    mapping: dict[str, EvidenceBoundItem] = {}
    for method in extraction.methods:
        mapping[method.method_id] = method
    for material in extraction.materials:
        mapping[material.material_id] = material
    for condition in extraction.conditions:
        mapping[condition.condition_id] = condition
    for metric in extraction.metrics:
        mapping[metric.metric_id] = metric
    for result in extraction.results:
        mapping[result.result_id] = result
    for conclusion in extraction.conclusions:
        mapping[conclusion.conclusion_id] = conclusion
    return mapping


def _entity_text(entity_id: str, entity: EvidenceBoundItem) -> str:
    name = getattr(entity, "name", "") or ""
    description = getattr(entity, "description", "") or ""
    return name or description or entity_id


def _user_prompt(entity_by_id: dict[str, EvidenceBoundItem], taxonomy: ProjectTaxonomy) -> str:
    lines = [_taxonomy_prompt(taxonomy), "", "Entities to tag:"]
    for entity_id, entity in entity_by_id.items():
        lines.append(f"- entity_id: {entity_id}\n  text: {_entity_text(entity_id, entity)}")
    return "\n".join(lines)


def _resolve_value(
    value: object,
    allowed_values: set[str],
    canonical_by_alias: dict[str, str],
) -> str | None:
    if not isinstance(value, str):
        return None
    if value in allowed_values:
        return value
    canonical = canonical_by_alias.get(value.lower())
    if canonical is not None and canonical in allowed_values:
        return canonical
    return None


def tag_extraction(
    extraction: PaperExtractionResult,
    taxonomy: ProjectTaxonomy,
    chat_client: ChatJSONClient,
) -> list[str]:
    """Tag already-extracted entities against a project's taxonomy via one
    strict-schema LLM call. Mutates the entities in `extraction` in place and
    sets `extraction.taxonomy_version`. Returns human-readable warnings for
    any tag the LLM proposed that didn't resolve against the taxonomy --
    resolution failures are dropped, never raised. LLM-call failures
    (network, malformed JSON) propagate as ExtractionError; the caller
    decides whether that's fatal."""
    warnings: list[str] = []
    entity_by_id = _entity_by_id(extraction)
    if not entity_by_id or not taxonomy.categories:
        extraction.taxonomy_version = taxonomy.version
        return warnings

    allowed_by_category = {
        category.key: set(category.allowed_values) for category in taxonomy.categories
    }
    canonical_by_alias = {
        category.key: {
            alias.lower(): value
            for value, aliases in category.aliases.items()
            for alias in aliases
        }
        for category in taxonomy.categories
    }

    payload = chat_client.extract_json(
        system_prompt=_load_tagging_prompt(),
        user_prompt=_user_prompt(entity_by_id, taxonomy),
    )
    raw_tags = payload.get("tags")
    if not isinstance(raw_tags, dict):
        extraction.taxonomy_version = taxonomy.version
        return warnings

    for entity_id, entity_tags in raw_tags.items():
        entity = entity_by_id.get(entity_id)
        if entity is None or not isinstance(entity_tags, dict):
            continue
        for category, value in entity_tags.items():
            allowed_values = allowed_by_category.get(category)
            if allowed_values is None:
                warnings.append(
                    f"Tagging: unknown category '{category}' for entity {entity_id}; dropped."
                )
                continue
            resolved = _resolve_value(value, allowed_values, canonical_by_alias[category])
            if resolved is None:
                warnings.append(
                    f"Tagging: value '{value}' for category '{category}' on entity "
                    f"{entity_id} is not in the taxonomy; dropped."
                )
                continue
            entity.tags[category] = resolved

    extraction.taxonomy_version = taxonomy.version
    return warnings
