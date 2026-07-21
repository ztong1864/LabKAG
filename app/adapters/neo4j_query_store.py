from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.adapters.neo4j_graph_store import Neo4jGraphStoreError
from app.schemas.evidence import Evidence


@dataclass
class EvidenceSearchResult:
    evidence: Evidence
    paper: dict[str, Any] = field(default_factory=dict)
    score: float = 0


@dataclass
class PaperEntityRow:
    paper_id: str
    paper_properties: dict[str, Any] = field(default_factory=dict)
    entities: list[dict[str, Any]] = field(default_factory=list)


class Neo4jQueryStore:
    VECTOR_INDEX_NAME = "labkag_evidence_embedding_index"

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        database: str = "neo4j",
        driver_factory: Callable | None = None,
    ) -> None:
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.driver_factory = driver_factory or self._default_driver_factory

    def search_evidence(
        self,
        query: str,
        *,
        project_id: str | None = None,
        paper_id: str | None = None,
        top_k: int = 10,
        query_embedding: list[float] | None = None,
    ) -> list[EvidenceSearchResult]:
        driver = self.driver_factory(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) as session:
                cypher = (
                    self._search_evidence_vector_cypher(paper_id=paper_id)
                    if query_embedding is not None
                    else self._search_evidence_keyword_cypher(paper_id=paper_id)
                )
                params = {
                    "search_text": query,
                    "project_id": project_id or "",
                    "paper_id": paper_id,
                    "limit": top_k,
                }
                if query_embedding is not None:
                    params["query_embedding"] = query_embedding
                try:
                    records = session.run(cypher, **params)
                except Exception:
                    if query_embedding is None:
                        raise
                    records = session.run(
                        self._search_evidence_keyword_cypher(paper_id=paper_id),
                        search_text=query,
                        project_id=project_id or "",
                        paper_id=paper_id,
                        limit=top_k,
                    )
                return [self._record_to_result(record) for record in records]
        finally:
            driver.close()

    def count_papers_with_tag_values(
        self, project_id: str, removals: list[dict[str, str]]
    ) -> int:
        """Count distinct papers that have an entity tagged with any of the
        given removed/renamed values, for taxonomy-edit breaking-change
        detection. `removals` is a list of {"property": "tag_<category>",
        "value": <value>} dicts."""
        if not removals:
            return 0
        driver = self.driver_factory(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) as session:
                records = session.run(
                    self._count_papers_with_tag_values_cypher(),
                    project_id=project_id,
                    removals=removals,
                )
                paper_ids = {
                    (record.data() if hasattr(record, "data") else dict(record))["paper_id"]
                    for record in records
                }
                return len(paper_ids)
        finally:
            driver.close()

    @staticmethod
    def _count_papers_with_tag_values_cypher() -> str:
        return """
        UNWIND $removals AS removal
        MATCH (p:Paper {project_id: $project_id})
              -[:proposes|uses|hasCondition|measures|reports|drawsConclusion]->(e)
        WHERE e.project_id = $project_id AND e[removal.property] = removal.value
        RETURN DISTINCT p.id AS paper_id
        """

    def list_papers(
        self, project_id: str, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        driver = self.driver_factory(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) as session:
                params: dict[str, Any] = {"project_id": project_id, "offset": offset}
                if limit is not None:
                    params["limit"] = limit
                records = session.run(self._list_papers_cypher(limit is not None), **params)
                return [
                    (record.data() if hasattr(record, "data") else dict(record))["paper"]
                    for record in records
                ]
        finally:
            driver.close()

    @staticmethod
    def _list_papers_cypher(has_limit: bool) -> str:
        limit_clause = "LIMIT $limit" if has_limit else ""
        return f"""
        MATCH (p:Paper)
        WHERE p.project_id = $project_id
        RETURN properties(p) AS paper
        ORDER BY p.id
        SKIP $offset
        {limit_clause}
        """

    def fetch_entities_for_topic_matching(
        self, project_id: str, limit: int = 5000, offset: int = 0
    ) -> list[PaperEntityRow]:
        """One graph-wide row per paper, each carrying every entity attached
        to it via the standard relation types, with the evidence_ids each
        entity cites (via supportedBy) so topic_matcher can detect
        co-occurrence through shared evidence. `limit` here is a safety cap
        on the fetch itself, unrelated to any confirmed/borderline result
        limit a caller applies afterward."""
        driver = self.driver_factory(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) as session:
                records = session.run(
                    self._fetch_entities_for_topic_matching_cypher(),
                    project_id=project_id,
                    offset=offset,
                    limit=limit,
                )
                return [self._record_to_paper_entity_row(record) for record in records]
        finally:
            driver.close()

    @staticmethod
    def _fetch_entities_for_topic_matching_cypher() -> str:
        return """
        MATCH (p:Paper)
        WHERE p.project_id = $project_id
        OPTIONAL MATCH (p)-[rel:proposes|uses|hasCondition|measures|reports|drawsConclusion]->(e)
        WHERE e IS NULL OR e.project_id = $project_id
        OPTIONAL MATCH (e)-[:supportedBy]->(ev:Evidence)
        WITH p, e, rel, collect(DISTINCT ev.evidence_id) AS evidence_ids
        WITH p, collect(
          CASE WHEN e IS NULL THEN NULL ELSE {
            entity_id: e.id, entity_type: labels(e)[0], relation: type(rel),
            properties: properties(e), evidence_ids: evidence_ids
          } END
        ) AS raw_entities
        RETURN p.id AS paper_id, properties(p) AS paper_properties,
               [x IN raw_entities WHERE x IS NOT NULL] AS entities
        ORDER BY p.id
        SKIP $offset
        LIMIT $limit
        """

    @classmethod
    def _record_to_paper_entity_row(cls, record: Any) -> PaperEntityRow:
        data = record.data() if hasattr(record, "data") else dict(record)
        return PaperEntityRow(
            paper_id=data.get("paper_id", ""),
            paper_properties=data.get("paper_properties") or {},
            entities=data.get("entities") or [],
        )

    @staticmethod
    def _default_driver_factory(uri: str, auth: tuple[str, str]):
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise Neo4jGraphStoreError(
                "neo4j package is required when GRAPH_BACKEND=neo4j."
            ) from exc
        return GraphDatabase.driver(uri, auth=auth)

    @staticmethod
    def _search_evidence_keyword_cypher(*, paper_id: str | None = None) -> str:
        paper_filter = "WHERE p.id = $paper_id" if paper_id else ""
        return f"""
        MATCH (e:Evidence)
        WITH e, properties(e) AS evidence
        WHERE ($project_id = '' OR evidence.project_id = $project_id)
          AND toLower(coalesce(evidence.source_text, evidence.sourceText, ''))
            CONTAINS toLower($search_text)
        OPTIONAL MATCH (p:Paper)-[:hasEvidence]->(e)
        {paper_filter}
        RETURN evidence, properties(p) AS paper, 1.0 AS score
        ORDER BY score DESC, evidence.id
        LIMIT $limit
        """

    @staticmethod
    def _search_evidence_vector_cypher(*, paper_id: str | None = None) -> str:
        paper_filter = "AND p.id = $paper_id" if paper_id else ""
        return f"""
        MATCH (e:Evidence)
          SEARCH e IN (
            VECTOR INDEX {Neo4jQueryStore.VECTOR_INDEX_NAME}
            FOR $query_embedding
            LIMIT $limit
          ) SCORE AS score
        MATCH (p:Paper)-[:hasEvidence]->(e)
        WITH e, p, score, properties(e) AS evidence
        WHERE ($project_id = '' OR evidence.project_id = $project_id)
          {paper_filter}
        RETURN evidence, properties(p) AS paper, score
        ORDER BY score DESC, evidence.id
        LIMIT $limit
        """

    @classmethod
    def _record_to_result(cls, record: Any) -> EvidenceSearchResult:
        data = record.data() if hasattr(record, "data") else dict(record)
        evidence_properties = data.get("evidence") or {}
        return EvidenceSearchResult(
            evidence=cls._evidence_from_properties(evidence_properties),
            paper=data.get("paper") or {},
            score=float(data.get("score") or 0),
        )

    @staticmethod
    def _evidence_from_properties(properties: dict[str, Any]) -> Evidence:
        return Evidence(
            evidence_id=properties.get("evidence_id")
            or properties.get("evidenceId")
            or properties.get("id", ""),
            document_id=properties.get("document_id") or properties.get("documentId") or "",
            chunk_id=properties.get("chunk_id") or properties.get("chunkId") or "",
            page=int(properties.get("page") or 0),
            section_title=properties.get("section_title") or properties.get("sectionTitle"),
            source_text=properties.get("source_text") or properties.get("sourceText") or "",
            offset_start=properties.get("offset_start") or properties.get("offsetStart"),
            offset_end=properties.get("offset_end") or properties.get("offsetEnd"),
            paper_id=properties.get("paper_id") or properties.get("paperId"),
        )
