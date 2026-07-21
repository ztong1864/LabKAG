from typing import Any

from app.adapters.neo4j_query_store import Neo4jQueryStore
from app.adapters.sqlite_query_store import SQLiteQueryStore
from app.config import Settings, settings


class QueryStoreFactoryError(RuntimeError):
    pass


def build_query_store(config: Settings = settings) -> Any:
    backend = config.graph_backend.lower()
    if backend == "sqlite":
        return SQLiteQueryStore(
            db_path=config.sqlite_db_path, embedding_dim=config.embedding_dim
        )
    if backend != "neo4j":
        raise QueryStoreFactoryError(f"Unsupported GRAPH_BACKEND: {config.graph_backend}")

    password = config.neo4j_password
    if not password:
        raise QueryStoreFactoryError("NEO4J_PASSWORD is required when GRAPH_BACKEND=neo4j.")

    return Neo4jQueryStore(
        uri=config.neo4j_uri,
        user=config.neo4j_user,
        password=password,
        database=config.neo4j_database,
    )
