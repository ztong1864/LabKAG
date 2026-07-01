import inspect
from typing import Any

from app.adapters.embedding_client import configured_embedding_client
from app.adapters.neo4j_query_store import Neo4jQueryStore
from app.config import settings
from app.schemas.evidence import Evidence


class KAGClient:
    def __init__(
        self,
        query_store: Any | None = None,
        embedding_client: Any | None = None,
    ) -> None:
        self.query_store = query_store
        self.embedding_client = embedding_client

    def query(
        self,
        question: str,
        project_id: str | None = None,
        paper_id: str | None = None,
        top_k: int = 5,
    ) -> dict:
        query_embedding = self._query_embedding(question)
        search_kwargs = {
            "project_id": project_id,
            "paper_id": paper_id,
            "top_k": top_k,
        }
        if query_embedding is not None:
            search_kwargs["query_embedding"] = query_embedding
        results = self._search_evidence(question, **search_kwargs)
        return self._answer_from_evidence(results)

    def search_evidence(
        self,
        query: str,
        project_id: str | None = None,
        paper_id: str | None = None,
        top_k: int = 10,
    ) -> list[Evidence]:
        query_embedding = self._query_embedding(query)
        search_kwargs = {
            "project_id": project_id,
            "paper_id": paper_id,
            "top_k": top_k,
        }
        if query_embedding is not None:
            search_kwargs["query_embedding"] = query_embedding
        return [
            result.evidence
            for result in self._search_evidence(query, **search_kwargs)
        ]

    def _query_store(self) -> Any:
        if self.query_store is not None:
            return self.query_store
        if settings.graph_backend != "neo4j":
            raise RuntimeError("Real KAG query requires GRAPH_BACKEND=neo4j for v0.1.")
        if not settings.neo4j_password:
            raise RuntimeError("NEO4J_PASSWORD is required for real KAG query.")
        self.query_store = Neo4jQueryStore(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
        return self.query_store

    def _query_embedding(self, text: str) -> list[float] | None:
        if not settings.enable_embedding:
            return None
        client = self.embedding_client or configured_embedding_client()
        if client is None:
            return None
        return client.embed_texts([text])[0]

    def _search_evidence(self, query: str, **search_kwargs: Any):
        query_store = self._query_store()
        if "query_embedding" in inspect.signature(query_store.search_evidence).parameters:
            return query_store.search_evidence(query, **search_kwargs)
        search_kwargs.pop("query_embedding", None)
        return query_store.search_evidence(query, **search_kwargs)

    @staticmethod
    def _answer_from_evidence(results: list[Any]) -> dict:
        if not results:
            return {
                "answer": "No matching evidence found.",
                "related_entities": [],
                "reasoning_path": [],
                "confidence": "low",
                "evidence": [],
            }

        evidence = [result.evidence for result in results]
        related_entities = []
        reasoning_path = []
        for result in results:
            paper = result.paper or {}
            paper_id = paper.get("id") or result.evidence.paper_id
            if paper_id:
                related_entities.append(
                    {"id": paper_id, "type": "Paper", "title": paper.get("title", "")}
                )
                reasoning_path.append(paper_id)
            reasoning_path.append(result.evidence.evidence_id)

        return {
            "answer": " ".join(item.source_text for item in evidence if item.source_text),
            "related_entities": related_entities,
            "reasoning_path": reasoning_path,
            "confidence": "medium",
            "evidence": evidence,
        }


kag_client = KAGClient()
