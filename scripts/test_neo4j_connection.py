#!/usr/bin/env python3
"""Quick standalone check that Neo4j is reachable with the configured
credentials, before running anything that depends on it (e.g. /v1/papers/ingest
or the taxonomy match-topic corroboration engine).

Usage (PowerShell):
    $env:NEO4J_URI="bolt://127.0.0.1:7687"
    $env:NEO4J_USER="neo4j"
    $env:NEO4J_PASSWORD="labkagneo4j"
    $env:NEO4J_DATABASE="neo4j"
    python scripts/test_neo4j_connection.py
"""
from __future__ import annotations

import os
import sys

from neo4j import GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

URI = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD")
DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")


def main() -> int:
    if not PASSWORD:
        print("ERROR: NEO4J_PASSWORD is not set.", file=sys.stderr)
        return 1

    print(f"Connecting to {URI} as {USER!r}, database {DATABASE!r} ...")
    driver = GraphDatabase.driver(URI, auth=(USER, PASSWORD))
    try:
        driver.verify_connectivity()
        with driver.session(database=DATABASE) as session:
            record = session.run("RETURN 1 AS ok").single()
            if record is None or record["ok"] != 1:
                print("ERROR: connected, but the test query returned no result.", file=sys.stderr)
                return 1
            counts = session.run(
                "MATCH (n) RETURN count(n) AS node_count"
            ).single()
            node_count = counts["node_count"] if counts else 0
    except AuthError as exc:
        print(f"ERROR: authentication failed -- {exc}", file=sys.stderr)
        return 1
    except ServiceUnavailable as exc:
        print(f"ERROR: could not reach Neo4j at {URI} -- {exc}", file=sys.stderr)
        return 1
    finally:
        driver.close()

    print("OK: connected successfully.")
    print(f"Existing nodes in database {DATABASE!r}: {node_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
