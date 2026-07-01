from app.schemas.extraction import PaperExtractionResult


def map_extraction_to_graph(extraction: PaperExtractionResult) -> dict:
    entities: list[dict] = []
    relations: list[dict] = []

    paper_id = extraction.paper.paper_id or f"paper_{extraction.document_id}"
    entities.append(
        {
            "id": paper_id,
            "type": "Paper",
            "properties": extraction.paper.model_dump(),
        }
    )

    for method in extraction.methods:
        entity_id = method.method_id
        entities.append({"id": entity_id, "type": "Method", "properties": method.model_dump()})
        relations.append({"source": paper_id, "relation": "proposes", "target": entity_id})
        for evidence in method.evidence:
            relations.append(
                {"source": entity_id, "relation": "supportedBy", "target": evidence.evidence_id}
            )

    for material in extraction.materials:
        entity_id = material.material_id
        entities.append({"id": entity_id, "type": "Material", "properties": material.model_dump()})
        relations.append({"source": paper_id, "relation": "uses", "target": entity_id})
        for evidence in material.evidence:
            relations.append(
                {"source": entity_id, "relation": "supportedBy", "target": evidence.evidence_id}
            )

    for condition in extraction.conditions:
        entity_id = condition.condition_id
        entities.append(
            {"id": entity_id, "type": "Condition", "properties": condition.model_dump()}
        )
        relations.append({"source": paper_id, "relation": "hasCondition", "target": entity_id})
        for evidence in condition.evidence:
            relations.append(
                {"source": entity_id, "relation": "supportedBy", "target": evidence.evidence_id}
            )

    for metric in extraction.metrics:
        entity_id = metric.metric_id
        entities.append({"id": entity_id, "type": "Metric", "properties": metric.model_dump()})
        relations.append({"source": paper_id, "relation": "measures", "target": entity_id})
        for evidence in metric.evidence:
            relations.append(
                {"source": entity_id, "relation": "supportedBy", "target": evidence.evidence_id}
            )

    for result in extraction.results:
        entity_id = result.result_id
        entities.append({"id": entity_id, "type": "Result", "properties": result.model_dump()})
        relations.append({"source": paper_id, "relation": "reports", "target": entity_id})
        for evidence in result.evidence:
            relations.append(
                {"source": entity_id, "relation": "supportedBy", "target": evidence.evidence_id}
            )

    for conclusion in extraction.conclusions:
        entity_id = conclusion.conclusion_id
        entities.append(
            {"id": entity_id, "type": "Conclusion", "properties": conclusion.model_dump()}
        )
        relations.append({"source": paper_id, "relation": "drawsConclusion", "target": entity_id})
        for evidence in conclusion.evidence:
            relations.append(
                {"source": entity_id, "relation": "supportedBy", "target": evidence.evidence_id}
            )

    for evidence in extraction.evidence:
        entities.append(
            {"id": evidence.evidence_id, "type": "Evidence", "properties": evidence.model_dump()}
        )
        relations.append(
            {"source": paper_id, "relation": "hasEvidence", "target": evidence.evidence_id}
        )

    return {"entities": entities, "relations": relations}
