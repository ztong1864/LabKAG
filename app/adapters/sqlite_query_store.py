import json
from pathlib import Path
from typing import Any

from app.adapters.neo4j_query_store import EvidenceSearchResult, PaperEntityRow
from app.adapters.sqlite_connection import connect, vec_available
from app.schemas.evidence import Evidence

_ENTITY_RELATION_TYPES = (
    "proposes",
    "uses",
    "hasCondition",
    "measures",
    "reports",
    "drawsConclusion",
)
_ENTITY_RELATION_PLACEHOLDERS = ",".join("?" for _ in _ENTITY_RELATION_TYPES)


class SQLiteQueryStore:
    def __init__(self, db_path: Path | str, embedding_dim: int = 1536) -> None:
        self.db_path = Path(db_path)
        self.embedding_dim = embedding_dim

    def search_evidence(
        self,
        query: str,
        *,
        project_id: str | None = None,
        paper_id: str | None = None,
        top_k: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[EvidenceSearchResult]:
        conn = connect(self.db_path, embedding_dim=self.embedding_dim)
        try:
            if query_embedding is not None and vec_available(conn):
                try:
                    return self._search_vector(
                        conn, query_embedding, project_id, paper_id, top_k
                    )
                except Exception:
                    pass  # fall through to keyword search, same fallback as Neo4jQueryStore
            return self._search_keyword(conn, query, project_id, paper_id, top_k)
        finally:
            conn.close()

    def _search_keyword(
        self,
        conn,
        query: str,
        project_id: str | None,
        paper_id: str | None,
        top_k: int,
    ) -> list[EvidenceSearchResult]:
        sql = (
            "SELECT e.id, e.properties, p.id, p.properties FROM nodes e "
            "LEFT JOIN edges he ON he.relation_type = 'hasEvidence' AND he.target_id = e.id "
            "LEFT JOIN nodes p ON p.id = he.source_id AND p.type = 'Paper' "
            "WHERE e.type = 'Evidence' "
            "AND lower(json_extract(e.properties, '$.source_text')) LIKE ?"
        )
        params: list[Any] = [f"%{query.lower()}%"]
        if project_id:
            sql += " AND e.project_id = ?"
            params.append(project_id)
        if paper_id:
            sql += " AND p.id = ?"
            params.append(paper_id)
        sql += " ORDER BY e.id LIMIT ?"
        params.append(top_k)

        rows = conn.execute(sql, params).fetchall()
        return [
            EvidenceSearchResult(
                evidence=self._evidence_from_properties(
                    evidence_id, json.loads(properties_json)
                ),
                paper=self._paper_dict(paper_id_col, paper_properties_json),
                score=1.0,
            )
            for evidence_id, properties_json, paper_id_col, paper_properties_json in rows
        ]

    def _search_vector(
        self,
        conn,
        query_embedding: list[float],
        project_id: str | None,
        paper_id: str | None,
        top_k: int,
    ) -> list[EvidenceSearchResult]:
        rows = conn.execute(
            "SELECT evidence_id, distance FROM evidence_vec "
            "WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (json.dumps(query_embedding), max(top_k * 3, top_k)),
        ).fetchall()

        results: list[EvidenceSearchResult] = []
        for evidence_id, distance in rows:
            node = conn.execute(
                "SELECT properties, project_id FROM nodes WHERE id = ? AND type = 'Evidence'",
                (evidence_id,),
            ).fetchone()
            if node is None:
                continue
            properties_json, node_project_id = node
            if project_id and node_project_id != project_id:
                continue
            paper_row = conn.execute(
                "SELECT p.id, p.properties FROM edges he "
                "JOIN nodes p ON p.id = he.source_id AND p.type = 'Paper' "
                "WHERE he.relation_type = 'hasEvidence' AND he.target_id = ?",
                (evidence_id,),
            ).fetchone()
            paper = self._paper_dict(*paper_row) if paper_row else {}
            if paper_id and paper.get("id") != paper_id:
                continue
            evidence = self._evidence_from_properties(evidence_id, json.loads(properties_json))
            score = 1.0 / (1.0 + distance)
            results.append(EvidenceSearchResult(evidence=evidence, paper=paper, score=score))
            if len(results) >= top_k:
                break
        return results

    def list_papers(
        self, project_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        conn = connect(self.db_path, embedding_dim=self.embedding_dim)
        try:
            sql = (
                "SELECT id, properties FROM nodes "
                "WHERE type = 'Paper' AND project_id = ? ORDER BY id"
            )
            params: list[Any] = [project_id]
            if limit is not None:
                sql += " LIMIT ? OFFSET ?"
                params += [limit, offset]
            elif offset:
                sql += " LIMIT -1 OFFSET ?"
                params += [offset]
            rows = conn.execute(sql, params).fetchall()
            return [self._paper_dict(node_id, properties_json) for node_id, properties_json in rows]
        finally:
            conn.close()

    def count_papers_with_tag_values(
        self, project_id: str, removals: list[dict[str, str]]
    ) -> int:
        """Count distinct papers that have an entity tagged with any of the
        given removed/renamed values, for taxonomy-edit breaking-change
        detection. `removals` is a list of {"property": "tag_<category>",
        "value": <value>} dicts -- same shape Neo4jQueryStore expects."""
        if not removals:
            return 0
        conn = connect(self.db_path, embedding_dim=self.embedding_dim)
        try:
            paper_ids: set[str] = set()
            for removal in removals:
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT p.id
                    FROM edges he
                    JOIN nodes e ON e.id = he.target_id
                    JOIN nodes p ON p.id = he.source_id AND p.type = 'Paper'
                    WHERE he.relation_type IN ({_ENTITY_RELATION_PLACEHOLDERS})
                      AND p.project_id = ? AND e.project_id = ?
                      AND json_extract(e.properties, '$.' || ?) = ?
                    """,
                    (
                        *_ENTITY_RELATION_TYPES,
                        project_id,
                        project_id,
                        removal["property"],
                        removal["value"],
                    ),
                ).fetchall()
                paper_ids.update(row[0] for row in rows)
            return len(paper_ids)
        finally:
            conn.close()

    def fetch_entities_for_topic_matching(
        self, project_id: str, limit: int = 5000, offset: int = 0
    ) -> list[PaperEntityRow]:
        """One row per (paper, entity) pair, aggregated in Python into one
        PaperEntityRow per paper -- same shape Neo4jQueryStore returns, so
        topic_matcher.py works identically against either backend. limit/
        offset apply to the paper list itself, not the underlying SQL rows,
        since a single paper's entities all need to be grouped together
        first; fine at this corpus scale (a safety cap, same caveat noted
        on the Neo4j version)."""
        conn = connect(self.db_path, embedding_dim=self.embedding_dim)
        try:
            sql = f"""
            SELECT p.id, p.properties, e.id, e.type, he.relation_type, e.properties,
                   GROUP_CONCAT(DISTINCT ev.id)
            FROM nodes p
            LEFT JOIN edges he ON he.source_id = p.id
                AND he.relation_type IN ({_ENTITY_RELATION_PLACEHOLDERS})
            LEFT JOIN nodes e ON e.id = he.target_id
            LEFT JOIN edges se ON se.source_id = e.id AND se.relation_type = 'supportedBy'
            LEFT JOIN nodes ev ON ev.id = se.target_id AND ev.type = 'Evidence'
            WHERE p.type = 'Paper' AND p.project_id = ?
            GROUP BY p.id, e.id
            ORDER BY p.id
            """
            rows = conn.execute(sql, (*_ENTITY_RELATION_TYPES, project_id)).fetchall()

            papers: dict[str, PaperEntityRow] = {}
            order: list[str] = []
            for (
                paper_id,
                paper_props_json,
                entity_id,
                entity_type,
                relation,
                entity_props_json,
                evidence_csv,
            ) in rows:
                if paper_id not in papers:
                    papers[paper_id] = PaperEntityRow(
                        paper_id=paper_id,
                        paper_properties=json.loads(paper_props_json) if paper_props_json else {},
                        entities=[],
                    )
                    order.append(paper_id)
                if entity_id is not None:
                    papers[paper_id].entities.append(
                        {
                            "entity_id": entity_id,
                            "entity_type": entity_type,
                            "relation": relation,
                            "properties": (
                                json.loads(entity_props_json) if entity_props_json else {}
                            ),
                            "evidence_ids": evidence_csv.split(",") if evidence_csv else [],
                        }
                    )

            result = [papers[pid] for pid in order]
            if offset:
                result = result[offset:]
            return result[:limit]
        finally:
            conn.close()

    @staticmethod
    def _paper_dict(paper_id: str | None, paper_properties_json: str | None) -> dict[str, Any]:
        if not paper_id:
            return {}
        paper = json.loads(paper_properties_json) if paper_properties_json else {}
        paper["id"] = paper_id
        return paper

    @staticmethod
    def _evidence_from_properties(evidence_id: str, properties: dict[str, Any]) -> Evidence:
        return Evidence(
            evidence_id=properties.get("evidence_id") or evidence_id,
            document_id=properties.get("document_id") or "",
            chunk_id=properties.get("chunk_id") or "",
            page=int(properties.get("page") or 0),
            section_title=properties.get("section_title"),
            source_text=properties.get("source_text") or "",
            offset_start=properties.get("offset_start"),
            offset_end=properties.get("offset_end"),
            paper_id=properties.get("paper_id"),
        )
