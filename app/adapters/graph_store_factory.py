from typing import Any

from app.adapters.neo4j_graph_store import Neo4jGraphStore
from app.adapters.sqlite_graph_store import SQLiteGraphStore
from app.config import Settings, settings


class GraphStoreFactoryError(RuntimeError):
    pass


def build_graph_store(config: Settings = settings) -> Any:
    backend = config.graph_backend.lower()
    if backend == "sqlite":
        return SQLiteGraphStore(
            db_path=config.sqlite_db_path, embedding_dim=config.embedding_dim
        )
    if backend != "neo4j":
        raise GraphStoreFactoryError(f"Unsupported GRAPH_BACKEND: {config.graph_backend}")

    password = config.neo4j_password
    if not password:
        raise GraphStoreFactoryError("NEO4J_PASSWORD is required when GRAPH_BACKEND=neo4j.")

    return Neo4jGraphStore(
        uri=config.neo4j_uri,
        user=config.neo4j_user,
        password=password,
        database=config.neo4j_database,
    )
