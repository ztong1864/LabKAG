import json
from pathlib import Path

from app.adapters.sqlite_connection import connect
from app.adapters.sqlite_graph_store import SQLiteGraphStore


def _graph_payload(evidence_embedding=None) -> dict:
    evidence_properties = {
        "evidence_id": "ev_001",
        "document_id": "doc_001",
        "chunk_id": "chunk_001",
        "page": 1,
        "source_text": "Catalyst A reached 95% conversion.",
        "paper_id": "paper_001",
    }
    if evidence_embedding is not None:
        evidence_properties["embedding"] = evidence_embedding
    return {
        "entities": [
            {"id": "paper_001", "type": "Paper", "properties": {"title": "Catalyst paper"}},
            {"id": "ev_001", "type": "Evidence", "properties": evidence_properties},
        ],
        "relations": [
            {"source": "paper_001", "relation": "hasEvidence", "target": "ev_001"},
        ],
    }


def test_write_graph_persists_nodes_and_edges(tmp_path: Path):
    store = SQLiteGraphStore(db_path=tmp_path / "graph.db")

    result = store.write_graph(_graph_payload(), project_id="labkag_demo")

    assert result == {"entities_created": 2, "relations_created": 1, "evidence_created": 1}

    conn = connect(tmp_path / "graph.db")
    try:
        node_rows = conn.execute("SELECT id, type, project_id FROM nodes ORDER BY id").fetchall()
        assert node_rows == [
            ("ev_001", "Evidence", "labkag_demo"),
            ("paper_001", "Paper", "labkag_demo"),
        ]
        edge_row = conn.execute(
            "SELECT source_id, relation_type, target_id FROM edges"
        ).fetchone()
        assert edge_row == ("paper_001", "hasEvidence", "ev_001")
    finally:
        conn.close()


def test_write_graph_excludes_id_from_stored_properties(tmp_path: Path):
    store = SQLiteGraphStore(db_path=tmp_path / "graph.db")
    payload = {
        "entities": [
            {
                "id": "paper_001",
                "type": "Paper",
                "properties": {"id": "paper_001", "title": "X"},
            }
        ],
        "relations": [],
    }

    store.write_graph(payload, project_id="labkag_demo")

    conn = connect(tmp_path / "graph.db")
    try:
        properties = json.loads(
            conn.execute("SELECT properties FROM nodes WHERE id = ?", ("paper_001",)).fetchone()[0]
        )
        assert "id" not in properties
        assert properties["title"] == "X"
    finally:
        conn.close()


def test_write_graph_upserts_on_conflict(tmp_path: Path):
    store = SQLiteGraphStore(db_path=tmp_path / "graph.db")
    payload = {
        "entities": [{"id": "paper_001", "type": "Paper", "properties": {"title": "First"}}],
        "relations": [],
    }
    store.write_graph(payload, project_id="labkag_demo")

    payload["entities"][0]["properties"]["title"] = "Second"
    store.write_graph(payload, project_id="labkag_demo")

    conn = connect(tmp_path / "graph.db")
    try:
        rows = conn.execute("SELECT id FROM nodes").fetchall()
        assert len(rows) == 1
        properties = json.loads(
            conn.execute("SELECT properties FROM nodes WHERE id = ?", ("paper_001",)).fetchone()[0]
        )
        assert properties["title"] == "Second"
    finally:
        conn.close()


def test_write_graph_stores_evidence_embedding_when_vec_available(tmp_path: Path):
    store = SQLiteGraphStore(db_path=tmp_path / "graph.db", embedding_dim=3)

    store.write_graph(_graph_payload(evidence_embedding=[0.1, 0.2, 0.3]), project_id="labkag_demo")

    conn = connect(tmp_path / "graph.db", embedding_dim=3)
    try:
        row = conn.execute(
            "SELECT evidence_id FROM evidence_vec WHERE evidence_id = ?", ("ev_001",)
        ).fetchone()
        assert row is not None
    finally:
        conn.close()
