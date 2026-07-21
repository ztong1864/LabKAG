from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from app.adapters import kag_query_adapter
from app.main import app
from app.schemas.evidence import Evidence
from app.schemas.extraction import (
    ExtractedMaterial,
    ExtractedResult,
    PaperExtractionResult,
    PaperMetadata,
)
from app.schemas.taxonomy import ProjectTaxonomy, TaxonomyCategory
from app.services import skill_orchestrator
from app.storage.taxonomy_store import taxonomy_store


class FakeChatClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def extract_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        return self.payload


class FakeKAGClient:
    def query(self, question, *, project_id=None, paper_id=None, top_k=5):
        return {
            "answer": "ok",
            "related_entities": [],
            "reasoning_path": [],
            "confidence": "medium",
            "evidence": [
                Evidence(
                    evidence_id="ev_001",
                    document_id="doc_001",
                    paper_id="paper_001",
                    chunk_id="chunk_001",
                    page=1,
                    source_text="A result",
                )
            ],
        }

    def search_evidence(self, query, *, project_id=None, paper_id=None, top_k=10):
        return [
            Evidence(
                evidence_id="ev_001",
                document_id="doc_001",
                paper_id="paper_001",
                chunk_id="chunk_001",
                page=1,
                source_text="A result",
            )
        ]


def _make_pdf(path: Path, text: str = "LabKAG API paper\nResults are evidence bound.") -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()


class FakeListPapersQueryStore:
    def __init__(self, papers):
        self.papers = papers
        self.calls = []

    def list_papers(self, project_id, limit=None, offset=0):
        self.calls.append({"project_id": project_id, "limit": limit, "offset": offset})
        return self.papers


def test_list_papers_route_strips_paper_embedding(monkeypatch):
    import app.api.papers as papers_module

    fake_store = FakeListPapersQueryStore(
        [
            {"id": "paper_001", "title": "Iron paper", "paper_embedding": [0.1, 0.2]},
            {"id": "paper_002", "title": "Copper paper"},
        ]
    )
    monkeypatch.setattr(papers_module, "build_query_store", lambda: fake_store)
    client = TestClient(app)

    response = client.get("/v1/papers", params={"project_id": "proj_1"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    papers = body["data"]["papers"]
    assert papers[0]["title"] == "Iron paper"
    assert "paper_embedding" not in papers[0]
    assert "paper_embedding" not in papers[1]
    assert fake_store.calls == [{"project_id": "proj_1", "limit": None, "offset": 0}]


def test_list_papers_route_surfaces_graph_query_failed(monkeypatch):
    import app.api.papers as papers_module
    from app.adapters.query_store_factory import QueryStoreFactoryError

    def _raise():
        raise QueryStoreFactoryError("NEO4J_PASSWORD is required when GRAPH_BACKEND=neo4j.")

    monkeypatch.setattr(papers_module, "build_query_store", _raise)
    client = TestClient(app)

    response = client.get("/v1/papers", params={"project_id": "proj_1"})

    assert response.status_code == 502
    assert response.json()["errors"][0]["code"] == "graph_query_failed"


def test_upload_accepts_pdf_and_rejects_non_pdf(tmp_path: Path):
    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    with pdf_path.open("rb") as file:
        response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["file_id"]
    assert body["data"]["file_name"] == "paper.pdf"

    response = client.post(
        "/v1/papers/upload",
        files={"file": ("paper.txt", b"not a pdf", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "unsupported_file_type"


def test_extract_paper_returns_extraction_and_evidence(tmp_path: Path, monkeypatch):
    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    def fake_extract(self, document, extract_level="basic"):
        evidence = Evidence(
            evidence_id="ev_001",
            document_id=document.document_id,
            chunk_id=document.chunks[0].chunk_id,
            page=document.chunks[0].page,
            section_title=document.chunks[0].section_title,
            source_text=document.chunks[0].text,
        )
        return PaperExtractionResult(
            document_id=document.document_id,
            paper=PaperMetadata(title="Catalyst Study", paper_id="paper_001"),
            results=[
                ExtractedResult(
                    result_id="res_001",
                    description="A result",
                    evidence=[evidence],
                )
            ],
            evidence=[evidence],
        )

    monkeypatch.setattr(skill_orchestrator, "configured_chat_client", lambda: FakeChatClient({}))
    monkeypatch.setattr(skill_orchestrator.LLMPaperExtractor, "extract", fake_extract)

    with pdf_path.open("rb") as file:
        upload_response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.post(
        "/v1/papers/extract",
        json={"file_id": file_id, "extract_level": "basic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["paper_extraction"]["document_id"]
    assert body["evidence"]
    assert body["metadata"]["request_id"]
    assert body["warnings"] == []


def _fake_extract_with_material(self, document, extract_level="basic"):
    return PaperExtractionResult(
        document_id=document.document_id,
        paper=PaperMetadata(title="Catalyst Study", paper_id="paper_001"),
        materials=[ExtractedMaterial(material_id="material_001", name="Fe(NO3)3")],
    )


def test_extract_paper_tags_entities_when_project_has_taxonomy(tmp_path: Path, monkeypatch):
    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    taxonomy_store.save_taxonomy(
        "proj_tagged",
        ProjectTaxonomy(
            project_id="proj_tagged",
            version=1,
            categories=[
                TaxonomyCategory(
                    key="catalyst_type",
                    allowed_values=["iron", "copper"],
                    aliases={"iron": ["Fe(NO3)3"]},
                )
            ],
        ).model_dump(mode="json"),
    )

    fake_tag_payload = {"tags": {"material_001": {"catalyst_type": "Fe(NO3)3"}}}
    monkeypatch.setattr(
        skill_orchestrator, "configured_chat_client", lambda: FakeChatClient(fake_tag_payload)
    )
    monkeypatch.setattr(
        skill_orchestrator.LLMPaperExtractor, "extract", _fake_extract_with_material
    )

    with pdf_path.open("rb") as file:
        upload_response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.post(
        "/v1/papers/extract",
        json={"file_id": file_id, "project_id": "proj_tagged", "extract_level": "basic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    material = body["data"]["paper_extraction"]["materials"][0]
    assert material["tags"] == {"catalyst_type": "iron"}
    assert body["data"]["paper_extraction"]["taxonomy_version"] == 1


def test_extract_paper_untagged_when_project_has_no_taxonomy(tmp_path: Path, monkeypatch):
    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    monkeypatch.setattr(skill_orchestrator, "configured_chat_client", lambda: FakeChatClient({}))
    monkeypatch.setattr(
        skill_orchestrator.LLMPaperExtractor, "extract", _fake_extract_with_material
    )

    with pdf_path.open("rb") as file:
        upload_response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.post(
        "/v1/papers/extract",
        json={"file_id": file_id, "project_id": "proj_no_taxonomy", "extract_level": "basic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["warnings"] == []
    material = body["data"]["paper_extraction"]["materials"][0]
    assert material["tags"] == {}
    assert body["data"]["paper_extraction"]["taxonomy_version"] is None


def test_extract_paper_fails_when_llm_is_unavailable(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(skill_orchestrator, "configured_chat_client", lambda: None)

    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    with pdf_path.open("rb") as file:
        upload_response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.post("/v1/papers/extract", json={"file_id": file_id})

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "extraction_failed"
    assert body["errors"][0]["message"] == "LLM extractor is not configured."


def test_extract_paper_returns_extraction_failed_when_llm_extractor_fails(
    tmp_path: Path,
    monkeypatch,
):
    from app.services.paper_extractor import ExtractionError, LLMPaperExtractor

    def raise_extraction_error(*args, **kwargs):
        raise ExtractionError("LLM response was not valid JSON.")

    monkeypatch.setattr(skill_orchestrator, "configured_chat_client", lambda: FakeChatClient({}))
    monkeypatch.setattr(LLMPaperExtractor, "extract", raise_extraction_error)

    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    with pdf_path.open("rb") as file:
        upload_response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )
    file_id = upload_response.json()["data"]["file_id"]

    response = client.post("/v1/papers/extract", json={"file_id": file_id})

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "extraction_failed"
    assert body["errors"][0]["message"] == "LLM response was not valid JSON."


def test_ingest_query_search_and_knowledge_routes(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(kag_query_adapter, "kag_client", FakeKAGClient())

    captured = {}

    def fake_write_graph(graph_payload, confirm=False, project_id=None):
        captured["graph_payload"] = graph_payload
        return {
            "paper_id": "paper_001",
            "entities_created": 2,
            "relations_created": 1,
            "evidence_created": 1,
            "dry_run": False,
        }

    monkeypatch.setattr(skill_orchestrator.graph_client, "write_graph", fake_write_graph)
    def fake_extract(self, document, extract_level="basic"):
        evidence = Evidence(
            evidence_id="ev_001",
            document_id=document.document_id,
            chunk_id=document.chunks[0].chunk_id,
            page=document.chunks[0].page,
            section_title=document.chunks[0].section_title,
            source_text=document.chunks[0].text,
        )
        return PaperExtractionResult(
            document_id=document.document_id,
            paper=PaperMetadata(title="A Test Paper", paper_id="paper_001"),
            results=[
                ExtractedResult(
                    result_id="res_001",
                    description="A result",
                    evidence=[evidence],
                )
            ],
            evidence=[evidence],
        )

    monkeypatch.setattr(skill_orchestrator, "configured_chat_client", lambda: FakeChatClient({}))
    monkeypatch.setattr(skill_orchestrator.LLMPaperExtractor, "extract", fake_extract)

    client = TestClient(app)
    pdf_path = tmp_path / "paper.pdf"
    _make_pdf(pdf_path)

    with pdf_path.open("rb") as file:
        upload_response = client.post(
            "/v1/papers/upload",
            files={"file": ("paper.pdf", file, "application/pdf")},
        )
    file_id = upload_response.json()["data"]["file_id"]

    extract = client.post("/v1/papers/extract", json={"file_id": file_id, "extract_level": "basic"})
    assert extract.status_code == 200
    paper_extraction = extract.json()["data"]["paper_extraction"]

    ingest = client.post(
        "/v1/papers/ingest",
        json={"project_id": "labkag_demo", "paper_extraction": paper_extraction, "confirm": True},
    )
    assert ingest.status_code == 200
    assert ingest.json()["data"]["entities_created"] >= 1
    assert captured["graph_payload"]["entities"]

    query = client.post(
        "/v1/literature/query",
        json={"question": "What does this paper report?", "project_id": "labkag_demo"},
    )
    assert query.status_code == 200
    assert query.json()["data"]["answer"]
    assert query.json()["evidence"]

    search = client.post(
        "/v1/evidence/search",
        json={"query": "result", "project_id": "labkag_demo", "top_k": 5},
    )
    assert search.status_code == 200
    assert isinstance(search.json()["evidence"], list)

    knowledge = client.get("/v1/papers/paper_001/knowledge?project_id=labkag_demo")
    assert knowledge.status_code == 200
    assert knowledge.json()["data"]["paper"]["title"] == "A Test Paper"
    assert knowledge.json()["evidence"]


def test_ingest_returns_graph_write_failed_when_client_fails(monkeypatch):
    from app.adapters.graph_client import GraphWriteError
    from app.services import skill_orchestrator

    def fail_write(*args, **kwargs):
        raise GraphWriteError("Neo4j write failed: server error")

    monkeypatch.setattr(skill_orchestrator.graph_client, "write_graph", fail_write)

    client = TestClient(app)
    response = client.post(
        "/v1/papers/ingest",
        json={
            "project_id": "labkag_demo",
            "paper_extraction": {"document_id": "doc_001"},
            "confirm": True,
        },
    )

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "graph_write_failed"


def test_literature_query_returns_kag_query_failed_when_adapter_fails(monkeypatch):
    from app.api import literature

    def fail_query(*args, **kwargs):
        raise RuntimeError("Neo4j query is not configured.")

    monkeypatch.setattr(literature, "query_literature", fail_query)

    client = TestClient(app)
    response = client.post(
        "/v1/literature/query",
        json={"question": "What was reported?", "project_id": "1"},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "kag_query_failed"


def test_evidence_search_returns_kag_query_failed_when_adapter_fails(monkeypatch):
    from app.api import evidence

    def fail_search(*args, **kwargs):
        raise RuntimeError("Neo4j query is not configured.")

    monkeypatch.setattr(evidence, "search_evidence", fail_search)

    client = TestClient(app)
    response = client.post(
        "/v1/evidence/search",
        json={"query": "conversion", "project_id": "1"},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "kag_query_failed"
