import scripts.backfill_taxonomy_tags as backfill_module
from app.schemas.extraction import ExtractedMaterial, PaperExtractionResult, PaperMetadata
from app.schemas.taxonomy import ProjectTaxonomy, TaxonomyCategory
from app.services.paper_extractor import ExtractionError
from app.storage.metadata_store import metadata_store
from scripts.backfill_taxonomy_tags import needs_retag, retag_one


class FakeChatClient:
    def __init__(self, payload):
        self.payload = payload

    def extract_json(self, *, system_prompt: str, user_prompt: str) -> dict:
        if isinstance(self.payload, str):
            raise ExtractionError(self.payload)
        return self.payload


class FakeGraphClient:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = []

    def write_graph(self, graph_payload, confirm=False, project_id=None):
        self.calls.append({"confirm": confirm, "project_id": project_id})
        if self.error is not None:
            raise self.error
        return {"entities_created": 1, "relations_created": 1, "evidence_created": 0}


def _taxonomy(version=2):
    return ProjectTaxonomy(
        project_id="proj_1",
        version=version,
        categories=[TaxonomyCategory(key="catalyst_type", allowed_values=["iron"])],
    )


def test_needs_retag_true_when_version_differs():
    extraction = PaperExtractionResult(document_id="doc_001", taxonomy_version=1)

    assert needs_retag(extraction, _taxonomy(version=2), force=False) is True


def test_needs_retag_false_when_version_matches():
    extraction = PaperExtractionResult(document_id="doc_001", taxonomy_version=2)

    assert needs_retag(extraction, _taxonomy(version=2), force=False) is False


def test_needs_retag_true_when_forced_regardless_of_version():
    extraction = PaperExtractionResult(document_id="doc_001", taxonomy_version=2)

    assert needs_retag(extraction, _taxonomy(version=2), force=True) is True


def test_retag_one_tags_saves_and_writes_graph(monkeypatch):
    extraction = PaperExtractionResult(
        document_id="doc_001",
        paper=PaperMetadata(paper_id="paper_001", title="Iron paper"),
        materials=[ExtractedMaterial(material_id="material_001", name="iron")],
    )
    metadata_store.save_extraction("doc_001", extraction.model_dump(mode="json"))
    fake_graph_client = FakeGraphClient()
    monkeypatch.setattr(backfill_module, "graph_client", fake_graph_client)
    chat_client = FakeChatClient({"tags": {"material_001": {"catalyst_type": "iron"}}})

    record = retag_one("doc_001", _taxonomy(version=2), chat_client, dry_run=False)

    assert record["status"] == "ok"
    assert record["warnings"] == []
    saved = metadata_store.load_extraction("doc_001")
    assert saved["materials"][0]["tags"] == {"catalyst_type": "iron"}
    assert saved["taxonomy_version"] == 2
    assert fake_graph_client.calls == [{"confirm": True, "project_id": "proj_1"}]


def test_retag_one_dry_run_does_not_confirm_graph_write(monkeypatch):
    extraction = PaperExtractionResult(document_id="doc_001")
    metadata_store.save_extraction("doc_001", extraction.model_dump(mode="json"))
    fake_graph_client = FakeGraphClient()
    monkeypatch.setattr(backfill_module, "graph_client", fake_graph_client)
    chat_client = FakeChatClient({"tags": {}})

    record = retag_one("doc_001", _taxonomy(version=2), chat_client, dry_run=True)

    assert record["status"] == "ok"
    assert fake_graph_client.calls == [{"confirm": False, "project_id": "proj_1"}]


def test_retag_one_reports_failure_when_extraction_missing():
    record = retag_one("does_not_exist", _taxonomy(), FakeChatClient({}), dry_run=False)

    assert record["status"] == "failed"
    assert "not found" in record["error"]


def test_retag_one_reports_failure_when_tagging_llm_fails():
    extraction = PaperExtractionResult(
        document_id="doc_001",
        materials=[ExtractedMaterial(material_id="material_001", name="iron")],
    )
    metadata_store.save_extraction("doc_001", extraction.model_dump(mode="json"))
    chat_client = FakeChatClient("LLM request failed with HTTP 500.")

    record = retag_one("doc_001", _taxonomy(), chat_client, dry_run=False)

    assert record["status"] == "failed"
    assert "500" in record["error"]


def test_retag_one_reports_failure_when_graph_write_fails(monkeypatch):
    extraction = PaperExtractionResult(document_id="doc_001")
    metadata_store.save_extraction("doc_001", extraction.model_dump(mode="json"))
    from app.adapters.graph_client import GraphWriteError

    fake_graph_client = FakeGraphClient(error=GraphWriteError("Neo4j unreachable"))
    monkeypatch.setattr(backfill_module, "graph_client", fake_graph_client)

    record = retag_one("doc_001", _taxonomy(), FakeChatClient({"tags": {}}), dry_run=False)

    assert record["status"] == "failed"
    assert "Neo4j unreachable" in record["error"]
