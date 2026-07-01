from app.config import settings
from app.schemas.evidence import Evidence
from app.schemas.extraction import ExtractedResult, PaperExtractionResult, PaperMetadata
from app.schemas.paper import IngestPaperRequest
from app.services import skill_orchestrator


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls = []

    def embed_texts(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3]]


def test_ingest_paper_attaches_evidence_embeddings_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_embedding", True)
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr(
        skill_orchestrator,
        "configured_embedding_client",
        lambda: FakeEmbeddingClient(),
    )

    captured = {}

    def fake_write_graph(graph_payload, confirm=False, project_id=None):
        captured["graph_payload"] = graph_payload
        return {
            "paper_id": "paper_001",
            "entities_created": 2,
            "relations_created": 1,
            "evidence_created": 1,
        }

    monkeypatch.setattr(skill_orchestrator.graph_client, "write_graph", fake_write_graph)

    request = IngestPaperRequest(
        project_id="1",
        confirm=True,
        paper_extraction=PaperExtractionResult(
            document_id="doc_001",
            paper=PaperMetadata(paper_id="paper_001", title="Embedding paper"),
            results=[
                ExtractedResult(
                    result_id="res_001",
                    description="Catalyst A reached 95% conversion.",
                    evidence=[
                        Evidence(
                            evidence_id="ev_001",
                            document_id="doc_001",
                            chunk_id="chunk_001",
                            page=1,
                            source_text="Catalyst A reached 95% conversion.",
                        )
                    ],
                )
            ],
            evidence=[
                Evidence(
                    evidence_id="ev_001",
                    document_id="doc_001",
                    chunk_id="chunk_001",
                    page=1,
                    source_text="Catalyst A reached 95% conversion.",
                )
            ],
        ),
    )

    response = skill_orchestrator.ingest_paper(request)

    assert response.status == "success"
    evidence_entities = [
        entity
        for entity in captured["graph_payload"]["entities"]
        if entity["type"] == "Evidence"
    ]
    assert evidence_entities[0]["properties"]["embedding"] == [0.1, 0.2, 0.3]
    assert evidence_entities[0]["properties"]["embedding_model"] == "text-embedding-3-small"
    assert evidence_entities[0]["properties"]["embedding_dim"] == 3
