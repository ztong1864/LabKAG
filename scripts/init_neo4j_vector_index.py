"""Create the Neo4j vector index used by LabKAG evidence retrieval."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

INDEX_NAME = "labkag_evidence_embedding_index"


def build_vector_index_cypher(index_name: str, dimensions: int) -> str:
    return f"""
    CREATE VECTOR INDEX {index_name} IF NOT EXISTS
    FOR (e:Evidence) ON (e.embedding)
    OPTIONS {{
      indexConfig: {{
        `vector.dimensions`: {dimensions},
        `vector.similarity_function`: 'cosine'
      }}
    }}
    """


def main() -> int:
    from app.config import settings

    if not settings.neo4j_password:
        print("NEO4J_PASSWORD is required.", file=sys.stderr)
        return 1

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    try:
        with driver.session(database=settings.neo4j_database) as session:
            session.run(build_vector_index_cypher(INDEX_NAME, settings.embedding_dim))
        print(f"Created or verified vector index: {INDEX_NAME}")
        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    raise SystemExit(main())
