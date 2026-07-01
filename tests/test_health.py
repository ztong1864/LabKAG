from fastapi.testclient import TestClient

from app.main import app


def test_health_returns_unified_success_response():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["service"] == "LabKAG"
    assert body["metadata"]["request_id"]
