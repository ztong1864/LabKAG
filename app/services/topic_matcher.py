from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from app.adapters.neo4j_query_store import PaperEntityRow
from app.schemas.taxonomy import MatchedPaper, ProjectTaxonomy, TopicConcept, TopicPlan

_ENGLISH_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

_RELATIVE_YEAR_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:past|last)\s+"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"years?(?![A-Za-z0-9])",
    re.IGNORECASE,
)


class TopicPlanError(RuntimeError):
    pass


def _resolve_value(
    value: str,
    allowed_values: set[str],
    canonical_by_alias: dict[str, str],
) -> str | None:
    if value in allowed_values:
        return value
    canonical = canonical_by_alias.get(value.lower())
    if canonical is not None and canonical in allowed_values:
        return canonical
    return None


def _derive_year_filter(topic: str, current_year: int) -> tuple[int | None, int | None]:
    match = _RELATIVE_YEAR_RE.search(topic)
    if not match:
        return None, None
    raw_count = match.group(1)
    count = int(raw_count) if raw_count.isdigit() else _ENGLISH_NUMBER_WORDS[raw_count.lower()]
    return current_year - count + 1, current_year


def verify_plan(
    plan: TopicPlan,
    taxonomy: ProjectTaxonomy,
    current_year: int | None = None,
) -> TopicPlan:
    """Deterministically verify an agent-proposed TopicPlan against a
    project's taxonomy -- no LLM call here. Drops any concept whose
    category/value doesn't resolve against the taxonomy (or an alias);
    raises TopicPlanError if that leaves zero essential concepts, or if the
    plan's stated year_from/year_to disagrees with an independent re-parse
    of a relative-year phrase in the topic text."""
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

    verified_concepts: list[TopicConcept] = []
    for concept in plan.concepts:
        allowed_values = allowed_by_category.get(concept.category)
        if allowed_values is None:
            continue
        resolved_value = _resolve_value(
            concept.value, allowed_values, canonical_by_alias[concept.category]
        )
        if resolved_value is None:
            continue
        verified_concepts.append(concept.model_copy(update={"value": resolved_value}))

    if not any(concept.essential for concept in verified_concepts):
        raise TopicPlanError(
            "Plan has no essential concepts that resolve against the project's taxonomy."
        )

    year = current_year if current_year is not None else datetime.now(timezone.utc).year
    derived_year_from, derived_year_to = _derive_year_filter(plan.topic, year)
    if (derived_year_from, derived_year_to) != (None, None) and (
        plan.year_from,
        plan.year_to,
    ) != (derived_year_from, derived_year_to):
        raise TopicPlanError(
            "Plan's year_from/year_to does not match an independent re-parse of the topic "
            f"text: plan=({plan.year_from}, {plan.year_to}) "
            f"derived=({derived_year_from}, {derived_year_to})."
        )

    return plan.model_copy(update={"concepts": verified_concepts})


def _collect_matches(concepts: list[TopicConcept], paper_row: PaperEntityRow) -> list[dict]:
    matches: list[dict] = []
    for entity in paper_row.entities:
        properties = entity.get("properties") or {}
        for concept in concepts:
            tag_value = properties.get(f"tag_{concept.category}")
            if tag_value == concept.value:
                matches.append(
                    {
                        "category": concept.category,
                        "value": concept.value,
                        "essential": concept.essential,
                        "entity_id": entity.get("entity_id"),
                        "entity_type": entity.get("entity_type"),
                        "evidence_ids": list(entity.get("evidence_ids") or []),
                    }
                )
    return matches


def _any_co_occurrence(matches: list[dict]) -> bool:
    for index, first in enumerate(matches):
        for second in matches[index + 1 :]:
            if first["category"] == second["category"]:
                continue
            if set(first["evidence_ids"]) & set(second["evidence_ids"]):
                return True
    return False


def _co_occurring_match(anchor: dict, matches: list[dict]) -> dict | None:
    anchor_evidence = set(anchor["evidence_ids"])
    if not anchor_evidence:
        return None
    for match in matches:
        if match is anchor:
            continue
        if match["category"] == anchor["category"] and match["value"] == anchor["value"]:
            continue
        if set(match["evidence_ids"]) & anchor_evidence:
            return match
    return None


def score_paper(
    concepts: list[TopicConcept],
    paper_row: PaperEntityRow,
    min_essential_signals: int,
) -> MatchedPaper | None:
    """Pure function, no I/O. Applies the corroboration tier rule: no single
    weak hit -- one keyword, one embedding nudge -- can ever produce
    `confirmed` on its own."""
    matches = _collect_matches(concepts, paper_row)
    if not matches:
        return None

    essential_categories = {match["category"] for match in matches if match["essential"]}
    co_occurrence = _any_co_occurrence(matches)
    reasons: list[str] = []
    tier: str

    if len(essential_categories) >= min_essential_signals:
        tier = "confirmed"
        reasons.append(
            f"{len(essential_categories)} distinct essential concepts matched: "
            f"{', '.join(sorted(essential_categories))}."
        )
    elif len(essential_categories) == 1:
        essential_category = next(iter(essential_categories))
        central_essential_matches = [
            match
            for match in matches
            if match["category"] == essential_category
            and match["essential"]
            and match["entity_type"] in ("Result", "Conclusion")
        ]
        corroborator = None
        for anchor in central_essential_matches:
            corroborator = _co_occurring_match(anchor, matches)
            if corroborator is not None:
                break
        if corroborator is not None:
            tier = "confirmed"
            reasons.append(
                f"'{essential_category}' matched on a Result/Conclusion entity and shares "
                f"evidence with '{corroborator['category']}={corroborator['value']}'."
            )
        else:
            tier = "borderline"
            reasons.append(
                f"Only one essential concept matched ('{essential_category}') with no "
                "corroborating co-occurrence."
            )
    else:
        if not any(not match["essential"] for match in matches):
            return None
        tier = "borderline"
        reasons.append("Only supporting (non-essential) concepts matched.")

    return MatchedPaper(
        paper_id=paper_row.paper_id,
        title=paper_row.paper_properties.get("title", ""),
        tier=tier,
        matched_concepts=[
            {key: value for key, value in match.items() if key != "evidence_ids"}
            for match in matches
        ],
        co_occurrence=co_occurrence,
        embedding_score=None,
        reasons=reasons,
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def match_topic(
    project_id: str,
    plan: TopicPlan,
    min_essential_signals: int,
    include_borderline: bool,
    limit: int | None,
    query_store: Any,
    embedding_client: Any | None,
) -> dict[str, Any]:
    rows = query_store.fetch_entities_for_topic_matching(project_id)

    confirmed: list[MatchedPaper] = []
    borderline: list[MatchedPaper] = []
    excluded_count = 0
    for row in rows:
        matched = score_paper(plan.concepts, row, min_essential_signals)
        if matched is None:
            excluded_count += 1
        elif matched.tier == "confirmed":
            confirmed.append(matched)
        else:
            borderline.append(matched)

    if embedding_client is not None and plan.topic.strip():
        topic_embedding = embedding_client.embed_texts([plan.topic])[0]
        row_by_paper_id = {row.paper_id: row for row in rows}
        for matched in confirmed + borderline:
            row = row_by_paper_id.get(matched.paper_id)
            paper_vector = row.paper_properties.get("paper_embedding") if row else None
            if paper_vector:
                matched.embedding_score = _cosine_similarity(topic_embedding, paper_vector)
        confirmed.sort(key=lambda m: m.embedding_score or 0, reverse=True)
        borderline.sort(key=lambda m: m.embedding_score or 0, reverse=True)

    if limit is not None:
        confirmed = confirmed[:limit]
        borderline = borderline[:limit]

    return {
        "confirmed": confirmed,
        "borderline": borderline if include_borderline else [],
        "summary": {
            "candidates_scanned": len(rows),
            "confirmed_count": len(confirmed),
            "borderline_count": len(borderline) if include_borderline else 0,
            "excluded_count": excluded_count,
        },
    }
