import json
import re
from collections.abc import Callable
from typing import Any


class Neo4jGraphStoreError(RuntimeError):
    pass


class Neo4jGraphStore:
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

    def write_graph(self, graph_payload: dict, *, project_id: str | None = None) -> dict:
        driver = self.driver_factory(self.uri, auth=(self.user, self.password))
        try:
            with driver.session(database=self.database) as session:
                for entity in graph_payload.get("entities", []):
                    label = self._safe_token(entity["type"])
                    properties = self._properties(entity.get("properties", {}))
                    properties["labkag_type"] = entity["type"]
                    properties["project_id"] = project_id or ""
                    session.run(
                        f"MERGE (n:`{label}` {{id: $id}}) "
                        "SET n += $properties "
                        "SET n.id = $id",
                        id=entity["id"],
                        properties=properties,
                    )

                for relation in graph_payload.get("relations", []):
                    relation_type = self._safe_token(relation["relation"])
                    session.run(
                        "MATCH (s {id: $source}) "
                        "MATCH (t {id: $target}) "
                        f"MERGE (s)-[r:`{relation_type}`]->(t) "
                        "SET r.project_id = $project_id",
                        source=relation["source"],
                        target=relation["target"],
                        project_id=project_id or "",
                    )
        finally:
            driver.close()

        entities = graph_payload.get("entities", [])
        return {
            "entities_created": len(entities),
            "relations_created": len(graph_payload.get("relations", [])),
            "evidence_created": len(
                [entity for entity in entities if entity.get("type") == "Evidence"]
            ),
        }

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
    def _safe_token(value: str) -> str:
        token = re.sub(r"[^A-Za-z0-9_]", "_", value)
        if not token:
            raise Neo4jGraphStoreError("Neo4j label or relationship type cannot be empty.")
        if token[0].isdigit():
            token = f"_{token}"
        return token

    @classmethod
    def _properties(cls, values: dict[str, Any]) -> dict[str, Any]:
        values = dict(values)
        tags = values.pop("tags", None)
        properties = {
            key: cls._property_value(value)
            for key, value in values.items()
            if value is not None and key != "id"
        }
        if isinstance(tags, dict):
            for category, value in tags.items():
                if value is not None:
                    properties[f"tag_{cls._safe_token(category)}"] = cls._property_value(value)
        return properties

    @staticmethod
    def _property_value(value: Any) -> Any:
        if isinstance(value, str | int | float | bool):
            return value
        if isinstance(value, list) and all(
            isinstance(item, str | int | float | bool) for item in value
        ):
            return value
        return json.dumps(value, ensure_ascii=False)
