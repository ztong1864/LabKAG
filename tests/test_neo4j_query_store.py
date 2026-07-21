from app.adapters.neo4j_query_store import Neo4jQueryStore


class FakeRecord(dict):
    def data(self):
        return dict(self)


class FakeSession:
    def __init__(self, records):
        self.records = records
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def run(self, query: str, **params):
        self.queries.append((query, params))
        return self.records


class FakeDriver:
    def __init__(self, records):
        self.fake_session = FakeSession(records)
        self.closed = False

    def session(self, database=None):
        self.database = database
        return self.fake_session

    def close(self):
        self.closed = True


def test_neo4j_query_store_searches_evidence_by_text_and_project():
    fake_driver = FakeDriver(
        [
            FakeRecord(
                evidence={
                    "id": "ev_001",
                    "evidence_id": "ev_001",
                    "document_id": "doc_001",
                    "chunk_id": "chunk_001",
                    "page": 3,
                    "source_text": "Catalyst A reached 95% conversion.",
                    "section_title": "Results",
                    "paper_id": "paper_001",
                },
                paper={"id": "paper_001", "title": "Catalyst paper"},
                score=1,
            )
        ]
    )
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    results = store.search_evidence("conversion", project_id="1", top_k=5)

    assert results[0].evidence.evidence_id == "ev_001"
    assert results[0].evidence.source_text == "Catalyst A reached 95% conversion."
    assert results[0].paper["title"] == "Catalyst paper"
    query, params = fake_driver.fake_session.queries[0]
    assert "MATCH (e:Evidence)" in query
    assert params == {"search_text": "conversion", "project_id": "1", "paper_id": None, "limit": 5}
    assert fake_driver.closed is True


def test_neo4j_query_store_filters_by_paper_id():
    fake_driver = FakeDriver([])
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    store.search_evidence("conversion", project_id="1", paper_id="paper_001", top_k=3)

    query, params = fake_driver.fake_session.queries[0]
    assert "WHERE p.id = $paper_id" in query
    assert query.index("WHERE ($project_id") < query.index("OPTIONAL MATCH")
    assert params["paper_id"] == "paper_001"
    assert params["limit"] == 3


def test_neo4j_query_store_uses_vector_index_when_query_embedding_is_provided():
    fake_driver = FakeDriver(
        [
            FakeRecord(
                evidence={
                    "id": "ev_001",
                    "evidence_id": "ev_001",
                    "document_id": "doc_001",
                    "chunk_id": "chunk_001",
                    "page": 3,
                    "source_text": "Catalyst A reached 95% conversion.",
                    "section_title": "Results",
                    "paper_id": "paper_001",
                },
                paper={"id": "paper_001", "title": "Catalyst paper"},
                score=0.98,
            )
        ]
    )
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    results = store.search_evidence(
        "conversion",
        project_id="1",
        paper_id="paper_001",
        top_k=5,
        query_embedding=[0.1, 0.2, 0.3],
    )

    assert results[0].evidence.evidence_id == "ev_001"
    query, params = fake_driver.fake_session.queries[0]
    assert "SEARCH e IN (" in query
    assert "VECTOR INDEX labkag_evidence_embedding_index" in query
    assert params["query_embedding"] == [0.1, 0.2, 0.3]
    assert params["limit"] == 5


def test_count_papers_with_tag_values_counts_distinct_papers():
    fake_driver = FakeDriver(
        [
            FakeRecord(paper_id="paper_001"),
            FakeRecord(paper_id="paper_002"),
            FakeRecord(paper_id="paper_001"),
        ]
    )
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    count = store.count_papers_with_tag_values(
        "proj_1", [{"property": "tag_catalyst_type", "value": "mercury"}]
    )

    assert count == 2
    query, params = fake_driver.fake_session.queries[0]
    assert "UNWIND $removals AS removal" in query
    assert "e[removal.property] = removal.value" in query
    assert params["project_id"] == "proj_1"
    assert params["removals"] == [{"property": "tag_catalyst_type", "value": "mercury"}]
    assert fake_driver.closed is True


def test_count_papers_with_tag_values_returns_zero_without_removals():
    fake_driver = FakeDriver([])
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    count = store.count_papers_with_tag_values("proj_1", [])

    assert count == 0
    assert fake_driver.fake_session.queries == []


def test_list_papers_returns_properties_and_omits_limit_when_none():
    fake_driver = FakeDriver(
        [
            FakeRecord(paper={"id": "paper_001", "title": "First"}),
            FakeRecord(paper={"id": "paper_002", "title": "Second"}),
        ]
    )
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    papers = store.list_papers("proj_1")

    assert papers == [
        {"id": "paper_001", "title": "First"},
        {"id": "paper_002", "title": "Second"},
    ]
    query, params = fake_driver.fake_session.queries[0]
    assert "LIMIT" not in query
    assert "limit" not in params
    assert params == {"project_id": "proj_1", "offset": 0}
    assert fake_driver.closed is True


def test_list_papers_includes_limit_and_offset_when_given():
    fake_driver = FakeDriver([])
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    store.list_papers("proj_1", limit=10, offset=5)

    query, params = fake_driver.fake_session.queries[0]
    assert "LIMIT $limit" in query
    assert params == {"project_id": "proj_1", "offset": 5, "limit": 10}


def test_fetch_entities_for_topic_matching_shapes_rows():
    fake_driver = FakeDriver(
        [
            FakeRecord(
                paper_id="paper_001",
                paper_properties={"id": "paper_001", "title": "Iron paper"},
                entities=[
                    {
                        "entity_id": "material_001",
                        "entity_type": "Material",
                        "relation": "uses",
                        "properties": {"tag_catalyst_type": "iron"},
                        "evidence_ids": ["ev_001"],
                    }
                ],
            )
        ]
    )
    store = Neo4jQueryStore(
        uri="neo4j://localhost:7687",
        user="neo4j",
        password="secret",
        database="neo4j",
        driver_factory=lambda uri, auth: fake_driver,
    )

    rows = store.fetch_entities_for_topic_matching("proj_1")

    assert len(rows) == 1
    assert rows[0].paper_id == "paper_001"
    assert rows[0].paper_properties["title"] == "Iron paper"
    assert rows[0].entities[0]["entity_id"] == "material_001"
    assert rows[0].entities[0]["evidence_ids"] == ["ev_001"]
    query, params = fake_driver.fake_session.queries[0]
    assert "OPTIONAL MATCH (e)-[:supportedBy]->(ev:Evidence)" in query
    assert "proposes|uses|hasCondition|measures|reports|drawsConclusion" in query
    assert params == {"project_id": "proj_1", "offset": 0, "limit": 5000}
    assert fake_driver.closed is True
