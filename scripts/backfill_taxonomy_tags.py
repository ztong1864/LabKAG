#!/usr/bin/env python3
"""Retag already-ingested papers against a project's current taxonomy.

Standalone CLI, no running LabKAG server required. Resumable: each paper is
checkpointed independently (progress printed as it goes, one paper's
failure never halts the rest), and already-current papers are skipped
unless --force. --dry-run scores and tags without writing to Neo4j, reusing
GraphClient's existing confirm=False no-write path.

Usage:
    python scripts/backfill_taxonomy_tags.py --project-id proj_1
    python scripts/backfill_taxonomy_tags.py --project-id proj_1 --force
    python scripts/backfill_taxonomy_tags.py --project-id proj_1 --dry-run
    python scripts/backfill_taxonomy_tags.py --project-id proj_1 --paper-id paper_001
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.graph_client import GraphWriteError, graph_client  # noqa: E402
from app.adapters.graph_mapper import map_extraction_to_graph  # noqa: E402
from app.adapters.query_store_factory import (  # noqa: E402
    QueryStoreFactoryError,
    build_query_store,
)
from app.schemas.extraction import PaperExtractionResult  # noqa: E402
from app.schemas.taxonomy import ProjectTaxonomy  # noqa: E402
from app.services.paper_extractor import ExtractionError, configured_chat_client  # noqa: E402
from app.services.taxonomy_tagger import tag_extraction  # noqa: E402
from app.storage.metadata_store import metadata_store  # noqa: E402
from app.storage.taxonomy_store import taxonomy_store  # noqa: E402


def needs_retag(extraction: PaperExtractionResult, taxonomy: ProjectTaxonomy, force: bool) -> bool:
    if force:
        return True
    return extraction.taxonomy_version != taxonomy.version


def retag_one(
    document_id: str,
    taxonomy: ProjectTaxonomy,
    chat_client: Any,
    dry_run: bool,
) -> dict[str, Any]:
    """Retag one already-ingested paper. Never raises -- every failure mode
    (missing extraction on disk, tagging LLM failure, graph write failure)
    is caught and returned as a failed status record so the caller's loop
    can continue past it."""
    payload = metadata_store.load_extraction(document_id)
    if payload is None:
        return {
            "document_id": document_id,
            "status": "failed",
            "error": "extraction not found on disk",
        }

    extraction = PaperExtractionResult.model_validate(payload)
    try:
        warnings = tag_extraction(extraction, taxonomy, chat_client)
    except ExtractionError as exc:
        return {"document_id": document_id, "status": "failed", "error": str(exc)}

    metadata_store.save_extraction(document_id, extraction.model_dump(mode="json"))

    graph_payload = map_extraction_to_graph(extraction)
    try:
        graph_client.write_graph(
            graph_payload, confirm=not dry_run, project_id=taxonomy.project_id
        )
    except GraphWriteError as exc:
        return {"document_id": document_id, "status": "failed", "error": str(exc)}

    return {"document_id": document_id, "status": "ok", "warnings": warnings}


def run(args: argparse.Namespace) -> int:
    taxonomy_payload = taxonomy_store.load_taxonomy(args.project_id)
    if taxonomy_payload is None:
        print(f"ERROR: no taxonomy configured for project {args.project_id}.", file=sys.stderr)
        return 2
    taxonomy = ProjectTaxonomy.model_validate(taxonomy_payload)

    chat_client = configured_chat_client()
    if chat_client is None:
        print("ERROR: LLM extractor is not configured.", file=sys.stderr)
        return 2

    try:
        papers = build_query_store().list_papers(args.project_id)
    except QueryStoreFactoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.paper_id:
        wanted = set(args.paper_id)
        papers = [paper for paper in papers if paper.get("id") in wanted]

    results: list[dict[str, Any]] = []
    for paper in papers:
        document_id = paper.get("document_id")
        if not document_id:
            print(f"[skip] {paper.get('id')} -- no document_id on Paper node")
            continue

        extraction_payload = metadata_store.load_extraction(document_id)
        if extraction_payload is None:
            print(f"[skip] {document_id} -- extraction not found on disk")
            continue
        extraction = PaperExtractionResult.model_validate(extraction_payload)
        if not needs_retag(extraction, taxonomy, args.force):
            print(f"[skip] {document_id} -- already tagged at taxonomy version {taxonomy.version}")
            continue

        record: dict[str, Any] = {}
        for attempt in range(1, args.max_attempts + 1):
            record = retag_one(document_id, taxonomy, chat_client, args.dry_run)
            record["attempts"] = attempt
            if record["status"] == "ok":
                break
            print(f"[retry] {document_id} attempt {attempt} failed: {record.get('error')}")

        results.append(record)
        if record["status"] == "ok":
            print(f"[ok] {document_id}")
        else:
            print(f"[failed] {document_id}: {record.get('error')}")

    ok_count = sum(1 for record in results if record["status"] == "ok")
    failed_count = len(results) - ok_count
    print(
        f"\n=== Summary ===\nRetagged: {ok_count}  Failed: {failed_count}  "
        f"Skipped/total scanned: {len(papers)}"
    )
    return 0 if failed_count == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retag already-ingested papers against a project's current taxonomy."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--paper-id", action="append", default=[], help="Retag only these paper ids. Repeatable."
    )
    parser.add_argument("--force", action="store_true", help="Retag even if already current.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Score and tag but don't write to Neo4j."
    )
    parser.add_argument("--max-attempts", type=int, default=3)
    return parser.parse_args()


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
