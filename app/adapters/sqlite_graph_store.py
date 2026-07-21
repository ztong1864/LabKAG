import json
from pathlib import Path

from app.adapters.sqlite_connection import connect, vec_available


class SQLiteGraphStoreError(RuntimeError):
    pass


class SQLiteGraphStore:
    def __init__(self, db_path: Path | str, embedding_dim: int = 1536) -> None:
        self.db_path = Path(db_path)
        self.embedding_dim = embedding_dim

    def write_graph(self, graph_payload: dict, *, project_id: str | None = None) -> dict:
        conn = connect(self.db_path, embedding_dim=self.embedding_dim)
        has_vec = vec_available(conn)
        try:
            with conn:
                for entity in graph_payload.get("entities", []):
                    raw_properties = dict(entity.get("properties", {}))
                    tags = raw_properties.pop("tags", None)
                    properties = {
                        key: value
                        for key, value in raw_properties.items()
                        if value is not None and key != "id"
                    }
                    if isinstance(tags, dict):
                        for category, value in tags.items():
                            if value is not None:
                                properties[f"tag_{category}"] = value
                    conn.execute(
                        "INSERT INTO nodes (id, type, project_id, properties) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET "
                        "type=excluded.type, project_id=excluded.project_id, "
                        "properties=excluded.properties",
                        (
                            entity["id"],
                            entity["type"],
                            project_id or "",
                            json.dumps(properties, ensure_ascii=False),
                        ),
                    )
                    if entity["type"] == "Evidence" and has_vec:
                        embedding = properties.get("embedding")
                        if embedding:
                            # vec0 virtual tables don't support ON CONFLICT/UPSERT --
                            # delete-then-insert instead.
                            conn.execute(
                                "DELETE FROM evidence_vec WHERE evidence_id = ?",
                                (entity["id"],),
                            )
                            conn.execute(
                                "INSERT INTO evidence_vec (evidence_id, embedding) VALUES (?, ?)",
                                (entity["id"], json.dumps(embedding)),
                            )

                for relation in graph_payload.get("relations", []):
                    conn.execute(
                        "INSERT INTO edges (source_id, relation_type, target_id, project_id) "
                        "VALUES (?, ?, ?, ?) "
                        "ON CONFLICT(source_id, relation_type, target_id) DO UPDATE SET "
                        "project_id=excluded.project_id",
                        (
                            relation["source"],
                            relation["relation"],
                            relation["target"],
                            project_id or "",
                        ),
                    )
        finally:
            conn.close()

        entities = graph_payload.get("entities", [])
        return {
            "entities_created": len(entities),
            "relations_created": len(graph_payload.get("relations", [])),
            "evidence_created": len(
                [entity for entity in entities if entity.get("type") == "Evidence"]
            ),
        }
