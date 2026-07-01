from app.adapters.kag_client import KAGClient
from app.adapters.kag_query_adapter import query_literature, search_evidence
from app.adapters.neo4j_query_store import EvidenceSearchResult
from app.schemas.evidence import Evidence
from app.schemas.paper import QueryLiteratureRequest, SearchEvidenceRequest


class FakeQueryStore:
    def __init__(self) -> None:
        self.calls = []

    def search_evidence(self, query, *, project_id=None, paper_id=None, top_k=10):
        self.calls.append(
            {"query": query, "project_id": project_id, "paper_id": paper_id, "top_k": top_k}
        )
        return [
            EvidenceSearchResult(
                evidence=Evidence(
                    evidence_id="ev_001",
                    document_id="doc_001",
                    paper_id="paper_001",
                    chunk_id="chunk_001",
                    page=1,
                    source_text="Catalyst A reached 95% conversion.",
                ),
                paper={"id": "paper_001", "title": "Catalyst paper"},
                score=1,
            )
        ]


def test_kag_client_searches_real_evidence_with_query_store():
    query_store = FakeQueryStore()
    client = KAGClient(query_store=query_store)

    evidence = client.search_evidence(
        "conversion",
        project_id="1",
        paper_id="paper_001",
        top_k=3,
    )

    assert evidence[0].evidence_id == "ev_001"
    assert query_store.calls == [
        {"query": "conversion", "project_id": "1", "paper_id": "paper_001", "top_k": 3}
    ]


def test_kag_client_builds_answer_from_real_evidence():
    query_store = FakeQueryStore()
    client = KAGClient(query_store=query_store)

    result = client.query(
        "What conversion was reported?",
        project_id="1",
        paper_id="paper_001",
        top_k=1,
    )

    assert result["answer"] == "Catalyst A reached 95% conversion."
    assert result["confidence"] == "medium"
    assert result["related_entities"] == [
        {"id": "paper_001", "type": "Paper", "title": "Catalyst paper"}
    ]
    assert result["reasoning_path"] == ["paper_001", "ev_001"]
    assert result["evidence"][0].evidence_id == "ev_001"


def test_kag_client_returns_empty_answer_when_no_real_evidence_matches():
    class EmptyQueryStore:
        def search_evidence(self, query, *, project_id=None, paper_id=None, top_k=10):
            return []

    client = KAGClient(query_store=EmptyQueryStore())

    result = client.query("missing", project_id="1")

    assert result["answer"] == "No matching evidence found."
    assert result["confidence"] == "low"
    assert result["evidence"] == []


def test_kag_client_builds_query_store_from_primary_neo4j_settings(monkeypatch):
    from app.config import settings

    created = {}

    class FakeNeo4jQueryStore:
        def __init__(self, *, uri, user, password, database):
            created.update(
                {"uri": uri, "user": user, "password": password, "database": database}
            )

        def search_evidence(self, query, *, project_id=None, paper_id=None, top_k=10):
            return []

    monkeypatch.setattr(settings, "graph_backend", "neo4j")
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://new-host:7687")
    monkeypatch.setattr(settings, "neo4j_user", "new-user")
    monkeypatch.setattr(settings, "neo4j_password", "new-password")
    monkeypatch.setattr(settings, "neo4j_database", "new-db")
    monkeypatch.setattr("app.adapters.kag_client.Neo4jQueryStore", FakeNeo4jQueryStore)

    client = KAGClient()
    client.search_evidence("conversion")

    assert created == {
        "uri": "bolt://new-host:7687",
        "user": "new-user",
        "password": "new-password",
        "database": "new-db",
    }


def test_kag_client_passes_query_embedding_when_embedding_is_enabled(monkeypatch):
    from app.config import settings

    calls = {}

    class FakeEmbeddingClient:
        def embed_texts(self, texts):
            calls["texts"] = list(texts)
            return [[0.1, 0.2, 0.3]]

    class FakeNeo4jQueryStore:
        def __init__(self, *, uri, user, password, database):
            self.uri = uri
            self.user = user
            self.password = password
            self.database = database

        def search_evidence(
            self,
            query,
            *,
            project_id=None,
            paper_id=None,
            top_k=10,
            query_embedding=None,
        ):
            calls["query"] = query
            calls["project_id"] = project_id
            calls["paper_id"] = paper_id
            calls["top_k"] = top_k
            calls["query_embedding"] = query_embedding
            return []

    monkeypatch.setattr(settings, "graph_backend", "neo4j")
    monkeypatch.setattr(settings, "neo4j_uri", "bolt://new-host:7687")
    monkeypatch.setattr(settings, "neo4j_user", "new-user")
    monkeypatch.setattr(settings, "neo4j_password", "new-password")
    monkeypatch.setattr(settings, "neo4j_database", "new-db")
    monkeypatch.setattr(settings, "enable_embedding", True)
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-3-small")
    monkeypatch.setattr("app.adapters.kag_client.Neo4jQueryStore", FakeNeo4jQueryStore)

    client = KAGClient(query_store=None)
    client.embedding_client = FakeEmbeddingClient()
    client.search_evidence("conversion", project_id="1", paper_id="paper_001", top_k=4)

    assert calls["texts"] == ["conversion"]
    assert calls["query_embedding"] == [0.1, 0.2, 0.3]
    assert calls["project_id"] == "1"
    assert calls["paper_id"] == "paper_001"
    assert calls["top_k"] == 4


def test_query_adapter_passes_request_scope_to_kag_client(monkeypatch):
    calls = []

    class FakeKAGClient:
        def query(self, question, *, project_id=None, paper_id=None, top_k=5):
            calls.append(
                {
                    "question": question,
                    "project_id": project_id,
                    "paper_id": paper_id,
                    "top_k": top_k,
                }
            )
            return {"answer": "ok", "evidence": []}

    monkeypatch.setattr("app.adapters.kag_query_adapter.kag_client", FakeKAGClient())

    query_literature(
        QueryLiteratureRequest(
            question="What was reported?",
            project_id="1",
            paper_id="paper_001",
            top_k=2,
        )
    )

    assert calls == [
        {
            "question": "What was reported?",
            "project_id": "1",
            "paper_id": "paper_001",
            "top_k": 2,
        }
    ]


def test_search_adapter_passes_request_scope_to_kag_client(monkeypatch):
    calls = []

    class FakeKAGClient:
        def search_evidence(self, query, *, project_id=None, paper_id=None, top_k=10):
            calls.append(
                {
                    "query": query,
                    "project_id": project_id,
                    "paper_id": paper_id,
                    "top_k": top_k,
                }
            )
            return []

    monkeypatch.setattr("app.adapters.kag_query_adapter.kag_client", FakeKAGClient())

    search_evidence(
        SearchEvidenceRequest(
            query="conversion",
            project_id="1",
            paper_id="paper_001",
            top_k=4,
        )
    )

    assert calls == [
        {
            "query": "conversion",
            "project_id": "1",
            "paper_id": "paper_001",
            "top_k": 4,
        }
    ]
