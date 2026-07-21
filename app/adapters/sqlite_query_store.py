import json
from pathlib import Path
from typing import Any

from app.adapters.neo4j_query_store import EvidenceSearchResult
from app.adapters.sqlite_connection import connect, vec_available
from app.schemas.evidence import Evidence


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
