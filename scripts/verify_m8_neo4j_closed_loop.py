"""Run the LabKAG M8 Neo4j-only closed-loop verification."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

M8_PROJECT_ID = "neo4j_only"
M8_PAPER_ID = "m8_neo4j_only_paper_001"
M8_EVIDENCE_ID = "m8_neo4j_only_ev_001"
M8_QUERY = "M8 Neo4j-only marker 2026"
M8_EVIDENCE_TEXT = "M8 Neo4j-only marker 2026: literature evidence is stored and queried."


def configure_environment() -> None:
    defaults = {
        "GRAPH_BACKEND": "neo4j",
        "NEO4J_URI": "bolt://127.0.0.1:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "labkagneo4j",
        "NEO4J_DATABASE": "neo4j",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def build_ingest_payload() -> dict[str, Any]:
    evidence = {
        "evidence_id": M8_EVIDENCE_ID,
        "document_id": "m8_neo4j_only_doc_001",
        "chunk_id": "m8_neo4j_only_chunk_001",
        "page": 1,
        "section_title": "Results",
        "source_text": M8_EVIDENCE_TEXT,
    }
    return {
        "project_id": M8_PROJECT_ID,
        "confirm": True,
        "paper_extraction": {
            "document_id": "m8_neo4j_only_doc_001",
            "paper": {
                "paper_id": M8_PAPER_ID,
                "title": "M8 Neo4j-only Verification Paper",
                "authors": ["LabKAG"],
                "year": "2026",
                "abstract": "Minimal Neo4j-only verification payload.",
            },
            "results": [
                {
                    "result_id": "m8_neo4j_only_result_001",
                    "description": "Evidence is stored in Neo4j.",
                    "result_type": "verification",
                    "evidence": [evidence],
                }
            ],
            "evidence": [evidence],
        },
    }


def require_success(response: Any, step: str) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"{step} failed with HTTP {response.status_code}: {response.text}")
    body = response.json()
    if body.get("status") != "success":
        raise RuntimeError(f"{step} failed: {body}")
    print(f"PASS {step}")
    return body


def main() -> int:
    configure_environment()

    try:
        from fastapi.testclient import TestClient

        from app.main import app

        client = TestClient(app)

        health = client.get("/health")
        if health.status_code != 200:
            raise RuntimeError(f"health failed with HTTP {health.status_code}: {health.text}")
        print("PASS health")

        ingest = require_success(
            client.post("/v1/papers/ingest", json=build_ingest_payload()),
            "ingest",
        )
        if ingest["data"].get("dry_run") is not False:
            raise RuntimeError(f"ingest did not use real backend: {ingest['data']}")
        if ingest["data"].get("evidence_created", 0) < 1:
            raise RuntimeError(f"ingest created no evidence: {ingest['data']}")

        search = require_success(
            client.post(
                "/v1/evidence/search",
                json={
                    "query": M8_QUERY,
                    "project_id": M8_PROJECT_ID,
                    "paper_id": M8_PAPER_ID,
                    "top_k": 5,
                },
            ),
            "evidence_search",
        )
        evidence_ids = [item["evidence_id"] for item in search["evidence"]]
        if evidence_ids != [M8_EVIDENCE_ID]:
            raise RuntimeError(f"unexpected evidence ids: {evidence_ids}")

        query = require_success(
            client.post(
                "/v1/literature/query",
                json={
                    "question": M8_QUERY,
                    "project_id": M8_PROJECT_ID,
                    "paper_id": M8_PAPER_ID,
                    "top_k": 5,
                },
            ),
            "literature_query",
        )
        if M8_EVIDENCE_TEXT not in query["data"].get("answer", ""):
            raise RuntimeError(f"answer does not cite expected evidence text: {query['data']}")

        print("M8 Neo4j-only closed loop verification passed.")
        return 0
    except Exception as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
