from pathlib import Path

from app.adapters.sqlite_graph_store import SQLiteGraphStore
from app.adapters.sqlite_query_store import SQLiteQueryStore


def _seed(db_path: Path, embedding_dim: int = 3) -> None:
    store = SQLiteGraphStore(db_path=db_path, embedding_dim=embedding_dim)
    store.write_graph(
        {
            "entities": [
                {"id": "paper_001", "type": "Paper", "properties": {"title": "Catalyst paper"}},
                {
                    "id": "ev_001",
                    "type": "Evidence",
                    "properties": {
                        "evidence_id": "ev_001",
                        "document_id": "doc_001",
                        "chunk_id": "chunk_001",
                        "page": 3,
                        "source_text": "Catalyst A reached 95% conversion.",
                        "embedding": [1.0, 0.0, 0.0],
                    },
                },
                {
                    "id": "ev_002",
                    "type": "Evidence",
                    "properties": {
                        "evidence_id": "ev_002",
                        "document_id": "doc_001",
                        "chunk_id": "chunk_002",
                        "page": 4,
                        "source_text": "Unrelated remark about the weather.",
                        "embedding": [0.0, 1.0, 0.0],
                    },
                },
            ],
            "relations": [
                {"source": "paper_001", "relation": "hasEvidence", "target": "ev_001"},
                {"source": "paper_001", "relation": "hasEvidence", "target": "ev_002"},
            ],
        },
        project_id="labkag_demo",
    )


def test_search_evidence_by_keyword_and_project(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    _seed(db_path)
    store = SQLiteQueryStore(db_path=db_path, embedding_dim=3)

    results = store.search_evidence("conversion", project_id="labkag_demo", top_k=5)

    assert len(results) == 1
    assert results[0].evidence.evidence_id == "ev_001"
    assert results[0].evidence.source_text == "Catalyst A reached 95% conversion."
    assert results[0].paper["id"] == "paper_001"
    assert results[0].paper["title"] == "Catalyst paper"


def test_search_evidence_filters_by_project_id(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    _seed(db_path)
    store = SQLiteQueryStore(db_path=db_path, embedding_dim=3)

    results = store.search_evidence("conversion", project_id="other_project", top_k=5)

    assert results == []


def test_search_evidence_filters_by_paper_id(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    _seed(db_path)
    store = SQLiteQueryStore(db_path=db_path, embedding_dim=3)

    results = store.search_evidence("weather", paper_id="paper_001", top_k=5)
    assert len(results) == 1

    results = store.search_evidence("weather", paper_id="some_other_paper", top_k=5)
    assert results == []


def test_search_evidence_vector_ranks_by_similarity(tmp_path: Path):
    db_path = tmp_path / "graph.db"
    _seed(db_path)
    store = SQLiteQueryStore(db_path=db_path, embedding_dim=3)

    results = store.search_evidence(
        "irrelevant query text",
        project_id="labkag_demo",
        top_k=5,
        query_embedding=[1.0, 0.0, 0.0],
    )

    assert results[0].evidence.evidence_id == "ev_001"
    assert results[0].score > results[1].score


def test_search_evidence_falls_back_to_keyword_when_vec_unavailable(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "graph.db"
    _seed(db_path)
    monkeypatch.setattr("app.adapters.sqlite_query_store.vec_available", lambda conn: False)
    store = SQLiteQueryStore(db_path=db_path, embedding_dim=3)

    results = store.search_evidence(
        "conversion",
        project_id="labkag_demo",
        top_k=5,
        query_embedding=[1.0, 0.0, 0.0],
    )

    assert len(results) == 1
    assert results[0].evidence.evidence_id == "ev_001"
    assert results[0].score == 1.0
