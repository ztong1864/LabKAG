from app.schemas.extraction import PaperExtractionResult, PaperMetadata
from app.schemas.paper import IngestPaperRequest
from app.services.skill_orchestrator import _find_existing_paper_id, ingest_paper


class FakeQueryStore:
    def __init__(self, papers):
        self._papers = papers
        self.calls = []

    def list_papers(self, project_id):
        self.calls.append(project_id)
        return self._papers


def test_find_existing_paper_id_matches_by_doi():
    store = FakeQueryStore(
        [{"id": "paper_existing", "title": "Some Title", "doi": "10.1000/xyz"}]
    )
    paper = PaperMetadata(title="A Different Title", doi="10.1000/XYZ")

    found = _find_existing_paper_id(store, "proj_1", paper)

    assert found == "paper_existing"


def test_find_existing_paper_id_matches_by_title_when_no_doi():
    store = FakeQueryStore([{"id": "paper_existing", "title": "Iron Catalysis Study"}])
    paper = PaperMetadata(title="iron catalysis study")

    found = _find_existing_paper_id(store, "proj_1", paper)

    assert found == "paper_existing"


def test_find_existing_paper_id_returns_none_when_no_match():
    store = FakeQueryStore([{"id": "paper_existing", "title": "Unrelated Paper"}])
    paper = PaperMetadata(title="A New Paper", doi="10.1000/new")

    assert _find_existing_paper_id(store, "proj_1", paper) is None


def test_find_existing_paper_id_returns_none_for_blank_identity():
    store = FakeQueryStore([{"id": "paper_existing", "title": "Something"}])
    paper = PaperMetadata(title="", doi="")

    assert _find_existing_paper_id(store, "proj_1", paper) is None
    assert store.calls == []


def test_find_existing_paper_id_returns_none_when_query_store_raises():
    class RaisingQueryStore:
        def list_papers(self, project_id):
            raise RuntimeError("NEO4J_PASSWORD is required")

    paper = PaperMetadata(title="Some Title")

    assert _find_existing_paper_id(RaisingQueryStore(), "proj_1", paper) is None


def test_ingest_paper_reuses_existing_paper_id_on_title_match(monkeypatch):
    import app.services.skill_orchestrator as skill_orchestrator

    fake_query_store = FakeQueryStore(
        [{"id": "paper_original", "title": "Duplicate Extraction Test"}]
    )
    monkeypatch.setattr(
        skill_orchestrator, "build_query_store", lambda: fake_query_store
    )

    captured = {}

    def fake_write_graph(graph_payload, confirm=False, project_id=None):
        captured["graph_payload"] = graph_payload
        return {
            "paper_id": graph_payload["entities"][0]["id"],
            "entities_created": len(graph_payload["entities"]),
            "relations_created": 0,
            "evidence_created": 0,
            "dry_run": False,
        }

    monkeypatch.setattr(skill_orchestrator.graph_client, "write_graph", fake_write_graph)

    extraction = PaperExtractionResult(
        document_id="doc_new",
        paper=PaperMetadata(paper_id="paper_fresh_random", title="Duplicate Extraction Test"),
    )
    request = IngestPaperRequest(
        project_id="proj_1", paper_extraction=extraction, confirm=True
    )

    ingest_paper(request)

    paper_entity = next(
        e for e in captured["graph_payload"]["entities"] if e["type"] == "Paper"
    )
    assert paper_entity["id"] == "paper_original"


def test_ingest_paper_keeps_own_id_when_no_existing_match(monkeypatch):
    import app.services.skill_orchestrator as skill_orchestrator

    fake_query_store = FakeQueryStore([])
    monkeypatch.setattr(
        skill_orchestrator, "build_query_store", lambda: fake_query_store
    )

    captured = {}

    def fake_write_graph(graph_payload, confirm=False, project_id=None):
        captured["graph_payload"] = graph_payload
        return {
            "paper_id": graph_payload["entities"][0]["id"],
            "entities_created": len(graph_payload["entities"]),
            "relations_created": 0,
            "evidence_created": 0,
            "dry_run": False,
        }

    monkeypatch.setattr(skill_orchestrator.graph_client, "write_graph", fake_write_graph)

    extraction = PaperExtractionResult(
        document_id="doc_new",
        paper=PaperMetadata(paper_id="paper_fresh_random", title="A Brand New Paper"),
    )
    request = IngestPaperRequest(
        project_id="proj_1", paper_extraction=extraction, confirm=True
    )

    ingest_paper(request)

    paper_entity = next(
        e for e in captured["graph_payload"]["entities"] if e["type"] == "Paper"
    )
    assert paper_entity["id"] == "paper_fresh_random"


def test_ingest_paper_skips_dedup_lookup_when_not_confirmed(monkeypatch):
    import app.services.skill_orchestrator as skill_orchestrator

    def _fail_if_called():
        raise AssertionError("build_query_store should not be called when confirm=False")

    monkeypatch.setattr(skill_orchestrator, "build_query_store", _fail_if_called)

    extraction = PaperExtractionResult(
        document_id="doc_new",
        paper=PaperMetadata(paper_id="paper_fresh_random", title="Dry Run Paper"),
    )
    request = IngestPaperRequest(
        project_id="proj_1", paper_extraction=extraction, confirm=False
    )

    result = ingest_paper(request)

    assert result.data["dry_run"] is True
