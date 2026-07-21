from fastapi.testclient import TestClient

from app.main import app


class FakeQueryStore:
    def __init__(self, affected_count: int = 0):
        self.affected_count = affected_count

    def count_papers_with_tag_values(self, project_id, removals):
        return self.affected_count


def test_get_taxonomy_returns_404_when_not_configured():
    client = TestClient(app)

    response = client.get("/v1/projects/proj_1/taxonomy")

    assert response.status_code == 404
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "taxonomy_not_configured"


def test_post_taxonomy_first_time_succeeds_and_get_returns_it():
    client = TestClient(app)
    payload = {
        "project_id": "proj_1",
        "categories": [
            {
                "key": "catalyst_type",
                "description": "The primary catalyst.",
                "allowed_values": ["iron", "copper"],
                "aliases": {"iron": ["Fe(NO3)3"]},
                "essential_by_default": True,
            }
        ],
    }

    post_response = client.post("/v1/projects/proj_1/taxonomy", json=payload)
    assert post_response.status_code == 200
    post_body = post_response.json()
    assert post_body["status"] == "success"
    assert post_body["data"]["applied"] is True
    assert post_body["data"]["taxonomy"]["version"] == 1

    get_response = client.get("/v1/projects/proj_1/taxonomy")
    assert get_response.status_code == 200
    get_body = get_response.json()
    assert get_body["status"] == "success"
    assert get_body["data"]["taxonomy"]["categories"][0]["key"] == "catalyst_type"


def test_post_taxonomy_breaking_edit_without_confirm_returns_needs_review(monkeypatch):
    import app.api.projects as projects_module

    client = TestClient(app)
    first = {
        "project_id": "proj_1",
        "categories": [{"key": "catalyst_type", "allowed_values": ["iron", "mercury"]}],
    }
    client.post("/v1/projects/proj_1/taxonomy", json=first)

    monkeypatch.setattr(
        projects_module, "build_query_store", lambda: FakeQueryStore(affected_count=5)
    )
    breaking = {
        "project_id": "proj_1",
        "categories": [{"key": "catalyst_type", "allowed_values": ["iron"]}],
    }

    response = client.post("/v1/projects/proj_1/taxonomy", json=breaking)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "needs_review"
    assert body["data"]["applied"] is False
    assert body["data"]["affected_papers_count"] == 5

    unchanged = client.get("/v1/projects/proj_1/taxonomy")
    assert unchanged.json()["data"]["taxonomy"]["version"] == 1


def test_post_taxonomy_breaking_edit_surfaces_graph_query_failed_when_store_unavailable(
    monkeypatch,
):
    import app.api.projects as projects_module
    from app.adapters.query_store_factory import QueryStoreFactoryError

    client = TestClient(app)
    first = {
        "project_id": "proj_1",
        "categories": [{"key": "catalyst_type", "allowed_values": ["iron", "mercury"]}],
    }
    client.post("/v1/projects/proj_1/taxonomy", json=first)

    def _raise():
        raise QueryStoreFactoryError("NEO4J_PASSWORD is required when GRAPH_BACKEND=neo4j.")

    monkeypatch.setattr(projects_module, "build_query_store", _raise)
    breaking = {
        "project_id": "proj_1",
        "categories": [{"key": "catalyst_type", "allowed_values": ["iron"]}],
    }

    response = client.post("/v1/projects/proj_1/taxonomy", json=breaking)

    assert response.status_code == 502
    body = response.json()
    assert body["status"] == "failed"
    assert body["errors"][0]["code"] == "graph_query_failed"


def test_post_taxonomy_breaking_edit_with_confirm_applies(monkeypatch):
    import app.api.projects as projects_module

    client = TestClient(app)
    first = {
        "project_id": "proj_1",
        "categories": [{"key": "catalyst_type", "allowed_values": ["iron", "mercury"]}],
    }
    client.post("/v1/projects/proj_1/taxonomy", json=first)

    monkeypatch.setattr(
        projects_module, "build_query_store", lambda: FakeQueryStore(affected_count=5)
    )
    breaking = {
        "project_id": "proj_1",
        "categories": [{"key": "catalyst_type", "allowed_values": ["iron"]}],
    }

    response = client.post(
        "/v1/projects/proj_1/taxonomy", json=breaking, params={"confirm": "true"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["applied"] is True

    updated = client.get("/v1/projects/proj_1/taxonomy")
    assert updated.json()["data"]["taxonomy"]["version"] == 2
