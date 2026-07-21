from pathlib import Path

import pytest

from app.adapters.neo4j_query_store import Neo4jQueryStore
from app.adapters.query_store_factory import QueryStoreFactoryError, build_query_store
from app.adapters.sqlite_query_store import SQLiteQueryStore
from app.config import Settings


def test_build_query_store_returns_neo4j_store_from_primary_settings():
    settings = Settings(
        graph_backend="neo4j",
        neo4j_uri="bolt://new-host:7687",
        neo4j_user="new-user",
        neo4j_password="new-password",
        neo4j_database="new-db",
    )

    store = build_query_store(settings)

    assert isinstance(store, Neo4jQueryStore)
    assert store.uri == "bolt://new-host:7687"
    assert store.user == "new-user"
    assert store.password == "new-password"
    assert store.database == "new-db"


def test_build_query_store_requires_neo4j_password():
    settings = Settings(graph_backend="neo4j", neo4j_password=None)

    with pytest.raises(QueryStoreFactoryError, match="NEO4J_PASSWORD is required"):
        build_query_store(settings)


def test_build_query_store_rejects_unknown_backend():
    settings = Settings(graph_backend="unknown")

    with pytest.raises(QueryStoreFactoryError, match="Unsupported GRAPH_BACKEND"):
        build_query_store(settings)


def test_build_query_store_returns_sqlite_store_without_neo4j_password(tmp_path: Path):
    settings = Settings(
        graph_backend="sqlite",
        sqlite_db_path=tmp_path / "graph.db",
        neo4j_password=None,
    )

    store = build_query_store(settings)

    assert isinstance(store, SQLiteQueryStore)
    assert store.db_path == tmp_path / "graph.db"
