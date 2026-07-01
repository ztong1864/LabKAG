import pytest

from app.adapters.graph_client import GraphClient, GraphWriteError
from app.adapters.graph_mapper import map_extraction_to_graph
from app.schemas.evidence import Evidence
from app.schemas.extraction import (
    ExtractedConclusion,
    ExtractedCondition,
    ExtractedMetric,
    ExtractedResult,
    PaperExtractionResult,
)


def _extraction() -> PaperExtractionResult:
    evidence = Evidence(
        evidence_id="ev_001",
        document_id="doc_001",
        chunk_id="chunk_001",
        page=1,
        source_text="Catalyst A reached 95% conversion.",
    )
    return PaperExtractionResult(
        document_id="doc_001",
        results=[
            ExtractedResult(
                result_id="res_001",
                description="Catalyst A reached 95% conversion.",
                evidence=[evidence],
            )
        ],
        conclusions=[
            ExtractedConclusion(
                conclusion_id="con_001",
                description="Catalyst A is active.",
                evidence=[evidence],
            )
        ],
        evidence=[evidence],
    )


def test_map_extraction_to_graph_includes_evidence_support_relations():
    graph = map_extraction_to_graph(_extraction())

    relation_keys = {
        (relation["source"], relation["relation"], relation["target"])
        for relation in graph["relations"]
    }

    assert ("res_001", "supportedBy", "ev_001") in relation_keys
    assert ("con_001", "supportedBy", "ev_001") in relation_keys


def test_map_extraction_to_graph_links_paper_to_evidence():
    graph = map_extraction_to_graph(_extraction())

    relation_keys = {
        (relation["source"], relation["relation"], relation["target"])
        for relation in graph["relations"]
    }

    assert ("paper_doc_001", "hasEvidence", "ev_001") in relation_keys


def test_map_extraction_to_graph_includes_conditions_and_metrics():
    extraction = _extraction()
    evidence = extraction.evidence[0]
    extraction.conditions = [
        ExtractedCondition(
            condition_id="cond_001",
            name="temperature",
            value="80",
            unit="C",
            evidence=[evidence],
        )
    ]
    extraction.metrics = [
        ExtractedMetric(
            metric_id="metric_001",
            name="conversion",
            value="95",
            unit="%",
            evidence=[evidence],
        )
    ]

    graph = map_extraction_to_graph(extraction)

    entity_keys = {(entity["id"], entity["type"]) for entity in graph["entities"]}
    relation_keys = {
        (relation["source"], relation["relation"], relation["target"])
        for relation in graph["relations"]
    }
    assert ("cond_001", "Condition") in entity_keys
    assert ("metric_001", "Metric") in entity_keys
    assert ("paper_doc_001", "hasCondition", "cond_001") in relation_keys
    assert ("paper_doc_001", "measures", "metric_001") in relation_keys
    assert ("cond_001", "supportedBy", "ev_001") in relation_keys
    assert ("metric_001", "supportedBy", "ev_001") in relation_keys


def test_graph_client_writes_through_graph_store_with_request_project_id():
    class FakeGraphStore:
        def __init__(self) -> None:
            self.calls = []

        def write_graph(self, graph_payload, *, project_id):
            self.calls.append({"graph_payload": graph_payload, "project_id": project_id})
            return {"entities_created": 1, "relations_created": 1, "evidence_created": 0}

    graph_store = FakeGraphStore()
    client = GraphClient(graph_store=graph_store)

    result = client.write_graph(
        {"entities": [{"id": "paper_001", "type": "Paper"}], "relations": []},
        confirm=True,
        project_id="request_project",
    )

    assert result == {
        "paper_id": "paper_001",
        "entities_created": 1,
        "relations_created": 1,
        "evidence_created": 0,
        "dry_run": False,
    }
    assert graph_store.calls == [
        {
            "graph_payload": {"entities": [{"id": "paper_001", "type": "Paper"}], "relations": []},
            "project_id": "request_project",
        }
    ]


def test_graph_client_converts_graph_store_errors(monkeypatch):
    from app.adapters.graph_store_factory import GraphStoreFactoryError

    def fail_build_graph_store(*args, **kwargs):
        raise GraphStoreFactoryError("NEO4J_PASSWORD is required when GRAPH_BACKEND=neo4j.")

    monkeypatch.setattr("app.adapters.graph_client.build_graph_store", fail_build_graph_store)
    client = GraphClient()

    with pytest.raises(GraphWriteError, match="NEO4J_PASSWORD is required"):
        client.write_graph({"entities": [], "relations": []}, confirm=True)
