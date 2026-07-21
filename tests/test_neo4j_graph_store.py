from app.adapters.neo4j_graph_store import Neo4jGraphStore


class FakeSession:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query: str, **params):
        self.queries.append((query, params))


class FakeDriver:
    def __init__(self) -> None:
        self.fake_session = FakeSession()
        self.closed = False

    def session(self, database=None):
        self.database = database
        return self.fake_session

    def close(self) -> None:
        self.closed = True


def test_neo4j_graph_store_writes_entities_and_relations():
    fake_driver = FakeDriver()
    store = Neo4jGraphStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    result = store.write_graph(
        {
            "entities": [
                {
                    "id": "paper_closed_loop_001",
                    "type": "Paper",
                    "properties": {"title": "Closed Loop", "authors": ["LabKAG"]},
                },
                {
                    "id": "ev_closed_loop_001",
                    "type": "Evidence",
                    "properties": {"source_text": "Evidence text.", "extra": {"nested": True}},
                },
            ],
            "relations": [
                {
                    "source": "paper_closed_loop_001",
                    "relation": "supportedBy",
                    "target": "ev_closed_loop_001",
                }
            ],
        },
        project_id="labkag_demo",
    )

    assert result == {
        "entities_created": 2,
        "relations_created": 1,
        "evidence_created": 1,
    }
    assert fake_driver.database == "neo4j"
    assert "MERGE (n:`Paper` {id: $id})" in fake_driver.fake_session.queries[0][0]
    assert fake_driver.fake_session.queries[0][1]["properties"]["title"] == "Closed Loop"
    assert fake_driver.fake_session.queries[1][1]["properties"]["extra"] == '{"nested": true}'
    assert "MERGE (s)-[r:`supportedBy`]->(t)" in fake_driver.fake_session.queries[2][0]
    assert fake_driver.closed is True


def test_neo4j_graph_store_flattens_tags_into_scalar_properties():
    fake_driver = FakeDriver()
    store = Neo4jGraphStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    store.write_graph(
        {
            "entities": [
                {
                    "id": "res_001",
                    "type": "Result",
                    "properties": {
                        "description": "Iron catalyzed the reaction.",
                        "tags": {"catalyst_type": "iron", "reaction-type": "oxidation"},
                    },
                },
            ],
            "relations": [],
        },
        project_id="labkag_demo",
    )

    properties = fake_driver.fake_session.queries[0][1]["properties"]
    assert properties["tag_catalyst_type"] == "iron"
    assert properties["tag_reaction_type"] == "oxidation"
    assert "tags" not in properties


def test_neo4j_graph_store_passes_float_list_properties_through_unmodified():
    fake_driver = FakeDriver()
    store = Neo4jGraphStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    store.write_graph(
        {
            "entities": [
                {
                    "id": "paper_001",
                    "type": "Paper",
                    "properties": {"paper_embedding": [0.1, 0.2, 0.3]},
                },
            ],
            "relations": [],
        },
        project_id="labkag_demo",
    )

    properties = fake_driver.fake_session.queries[0][1]["properties"]
    assert properties["paper_embedding"] == [0.1, 0.2, 0.3]
