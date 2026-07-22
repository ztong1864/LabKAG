#!/usr/bin/env python3
"""Remove duplicate Paper nodes (same project_id + title) from the SQLite
graph backend, keeping the earliest (lowest id) of each duplicate group and
cascade-deleting everything exclusively reachable from the ones removed
(entities via the standard relation types, evidence via supportedBy/
hasEvidence, and every edge touching a deleted node).

Safe for this schema because every extraction creates its own freshly
random-ID'd entities -- nothing reached from one paper's edges is ever
shared with another paper, so cascade deletion can't orphan or corrupt an
unrelated paper's data.

Usage:
    python scripts/dedupe_papers.py --project-id xmart_55 --dry-run
    python scripts/dedupe_papers.py --project-id xmart_55
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.sqlite_connection import connect  # noqa: E402

_ENTITY_RELATION_TYPES = (
    "proposes",
    "uses",
    "hasCondition",
    "measures",
    "reports",
    "drawsConclusion",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove duplicate Paper nodes by title.")
    parser.add_argument("--db-path", default="data/graph.db")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Report only, delete nothing.")
    return parser.parse_args()


def find_duplicate_groups(conn, project_id: str) -> list[list[tuple[str, str]]]:
    """Returns a list of duplicate groups; each group is a list of
    (paper_id, title) tuples, sorted so [0] is the one to KEEP."""
    rows = conn.execute(
        "SELECT id, json_extract(properties, '$.title') AS title "
        "FROM nodes WHERE type = 'Paper' AND project_id = ? ORDER BY id",
        (project_id,),
    ).fetchall()

    by_title: dict[str, list[tuple[str, str]]] = {}
    for paper_id, title in rows:
        by_title.setdefault(title or "", []).append((paper_id, title))

    return [group for group in by_title.values() if len(group) > 1]


def cascade_delete_paper(conn, paper_id: str) -> dict[str, int]:
    entity_rows = conn.execute(
        "SELECT DISTINCT target_id FROM edges WHERE source_id = ? AND relation_type IN "
        f"({','.join('?' for _ in _ENTITY_RELATION_TYPES)})",
        (paper_id, *_ENTITY_RELATION_TYPES),
    ).fetchall()
    entity_ids = [row[0] for row in entity_rows]

    evidence_ids: set[str] = set()
    for entity_id in entity_ids:
        rows = conn.execute(
            "SELECT target_id FROM edges WHERE source_id = ? AND relation_type = 'supportedBy'",
            (entity_id,),
        ).fetchall()
        evidence_ids.update(row[0] for row in rows)
    direct_evidence = conn.execute(
        "SELECT target_id FROM edges WHERE source_id = ? AND relation_type = 'hasEvidence'",
        (paper_id,),
    ).fetchall()
    evidence_ids.update(row[0] for row in direct_evidence)

    all_node_ids = [paper_id, *entity_ids, *evidence_ids]
    placeholders = ",".join("?" for _ in all_node_ids)

    conn.execute(
        f"DELETE FROM edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
        (*all_node_ids, *all_node_ids),
    )
    conn.execute(f"DELETE FROM nodes WHERE id IN ({placeholders})", all_node_ids)
    try:
        conn.execute(
            f"DELETE FROM evidence_vec WHERE evidence_id IN ({placeholders})", all_node_ids
        )
    except Exception:
        pass  # evidence_vec may not exist if sqlite-vec never loaded

    return {"entities_removed": len(entity_ids), "evidence_removed": len(evidence_ids)}


def main() -> int:
    args = parse_args()
    conn = connect(args.db_path)
    try:
        groups = find_duplicate_groups(conn, args.project_id)
        if not groups:
            print(f"No duplicate papers found for project {args.project_id!r}.")
            return 0

        total_removed_papers = 0
        for group in groups:
            keep_id, title = group[0]
            remove = group[1:]
            print(f"'{title}' -- {len(group)} copies, keeping {keep_id}")
            for paper_id, _ in remove:
                if args.dry_run:
                    print(f"  [dry-run] would remove {paper_id}")
                else:
                    stats = cascade_delete_paper(conn, paper_id)
                    print(f"  removed {paper_id} ({stats})")
                total_removed_papers += 1

        if not args.dry_run:
            conn.commit()
        print(f"\n=== Summary ===\nDuplicate groups: {len(groups)}")
        print(f"Papers {'that would be' if args.dry_run else ''} removed: {total_removed_papers}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
