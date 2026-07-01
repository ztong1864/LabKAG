import pytest
import requests

from app.adapters.openspg_client import OpenSPGClient, OpenSPGClientError
from app.adapters.openspg_mapper import map_extraction_to_graph
from app.config import Settings
from app.schemas.evidence import Evidence
from app.schemas.extraction import (
    ExtractedConclusion,
    ExtractedCondition,
    ExtractedMetric,
    ExtractedResult,
    PaperExtractionResult,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict:
        return self._payload


class FakeSession:
    def __init__(self, response: FakeResponse | list[FakeResponse]) -> None:
        self.responses = response if isinstance(response, list) else [response]
        self.posts: list[dict] = []
        self.gets: list[dict] = []

    def post(self, url, *, headers, json, timeout):
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return self.responses.pop(0)

    def get(self, url, *, headers, params, timeout):
        self.gets.append({"url": url, "headers": headers, "params": params, "timeout": timeout})
        return self.responses.pop(0)


def _extraction() -> PaperExtractionResult:
    evidence = Evidence(
        evidence_id="ev_001",
        document_id="doc_001",
        chunk_id="chunk_001",
        page=1,
        source_text="Catalyst A reached 95% conversion.",
    )
    return PaperExtractionResult(
        document_id="doc_001",
        results=[
            ExtractedResult(
                result_id="res_001",
                description="Catalyst A reached 95% conversion.",
                evidence=[evidence],
            )
        ],
        conclusions=[
            ExtractedConclusion(
                conclusion_id="con_001",
                description="Catalyst A is active.",
                evidence=[evidence],
            )
        ],
        evidence=[evidence],
    )


def test_map_extraction_to_graph_includes_evidence_support_relations():
    graph = map_extraction_to_graph(_extraction())

    relation_keys = {
        (relation["source"], relation["relation"], relation["target"])
        for relation in graph["relations"]
    }

    assert ("res_001", "supportedBy", "ev_001") in relation_keys
    assert ("con_001", "supportedBy", "ev_001") in relation_keys


def test_map_extraction_to_graph_links_paper_to_evidence():
    graph = map_extraction_to_graph(_extraction())

    relation_keys = {
        (relation["source"], relation["relation"], relation["target"])
        for relation in graph["relations"]
    }

    assert ("paper_doc_001", "hasEvidence", "ev_001") in relation_keys


def test_map_extraction_to_graph_includes_conditions_and_metrics():
    extraction = _extraction()
    evidence = extraction.evidence[0]
    extraction.conditions = [
        ExtractedCondition(
            condition_id="cond_001",
            name="temperature",
            value="80",
            unit="C",
            evidence=[evidence],
        )
    ]
    extraction.metrics = [
        ExtractedMetric(
            metric_id="metric_001",
            name="conversion",
            value="95",
            unit="%",
            evidence=[evidence],
        )
    ]

    graph = map_extraction_to_graph(extraction)

    entity_keys = {(entity["id"], entity["type"]) for entity in graph["entities"]}
    relation_keys = {
        (relation["source"], relation["relation"], relation["target"])
        for relation in graph["relations"]
    }
    assert ("cond_001", "Condition") in entity_keys
    assert ("metric_001", "Metric") in entity_keys
    assert ("paper_doc_001", "hasCondition", "cond_001") in relation_keys
    assert ("paper_doc_001", "measures", "metric_001") in relation_keys
    assert ("cond_001", "supportedBy", "ev_001") in relation_keys
    assert ("metric_001", "supportedBy", "ev_001") in relation_keys


def test_openspg_client_posts_graph_payload_when_confirmed_and_not_mocked():
    session = FakeSession(
        FakeResponse(
            status_code=200,
            payload={
                "paper_id": "paper_001",
                "entities_created": 3,
                "relations_created": 2,
                "evidence_created": 1,
            },
        )
    )
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        write_path="/api/graph/write",
        api_key="secret",
        project_id="labkag",
        timeout_seconds=12,
        mock=False,
        session=session,
    )

    result = client.write_graph({"entities": [{"id": "paper_001"}], "relations": []}, confirm=True)

    assert result["entities_created"] == 3
    assert session.posts[0]["url"] == "https://openspg.example.com/api/graph/write"
    assert session.posts[0]["headers"]["Authorization"] == "Bearer secret"
    assert session.posts[0]["headers"]["X-OpenSPG-Project"] == "labkag"
    assert session.posts[0]["json"]["entities"] == [{"id": "paper_001"}]
    assert session.posts[0]["timeout"] == 12


def test_openspg_client_raises_clear_error_for_failed_write():
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        mock=False,
        session=FakeSession(FakeResponse(status_code=500, text="server error")),
    )

    with pytest.raises(OpenSPGClientError, match="OpenSPG write failed with HTTP 500"):
        client.write_graph({"entities": [], "relations": []}, confirm=True)


def test_openspg_client_raises_clear_error_for_business_failure():
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        mock=False,
        session=FakeSession(
            FakeResponse(
                status_code=200,
                payload={"success": False, "errorCode": "LOGIN_0002", "url": "/#/login"},
            )
        ),
    )

    with pytest.raises(OpenSPGClientError, match="business error LOGIN_0002"):
        client.write_graph({"entities": [], "relations": []}, confirm=True)


def test_openspg_login_posts_sha256_password_before_remote_write():
    session = FakeSession(
        [
            FakeResponse(status_code=200, payload={"success": True, "result": True}),
            FakeResponse(status_code=200, payload={"entities_created": 1}),
        ]
    )
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        write_path="/v1/not-yet-real-write",
        account="openspg",
        password="openspg123",
        mock=False,
        session=session,
    )

    client.write_graph({"entities": [{"id": "paper_001"}], "relations": []}, confirm=True)

    assert session.posts[0]["url"] == "https://openspg.example.com/v1/accounts/login"
    assert session.posts[0]["json"] == {
        "account": "openspg",
        "password": "dc8c309d752c00f9d348e4dc870b3292ce2c152fec4e50c7648cfbb1998d4e55",
    }
    assert session.posts[1]["url"] == "https://openspg.example.com/v1/not-yet-real-write"


def test_openspg_login_business_failure_raises_clear_error():
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        account="openspg",
        password="wrong",
        mock=False,
        session=FakeSession(
            FakeResponse(
                status_code=200,
                payload={
                    "success": False,
                    "errorCode": "illegal params",
                    "errorMsg": "user or password error",
                },
            )
        ),
    )

    with pytest.raises(OpenSPGClientError, match="OpenSPG login failed"):
        client.write_graph({"entities": [], "relations": []}, confirm=True)


def test_openspg_account_settings_are_loaded_from_env(monkeypatch):
    monkeypatch.setenv("OPENSPG_ACCOUNT", "openspg")
    monkeypatch.setenv("OPENSPG_PASSWORD", "openspg123")
    monkeypatch.setenv("OPENSPG_PROJECT_NAME", "LabKAG")
    monkeypatch.setenv("OPENSPG_NAMESPACE", "LabKAG")
    monkeypatch.setenv("OPENSPG_WRITE_BACKEND", "neo4j")
    monkeypatch.setenv("OPENSPG_NEO4J_URI", "neo4j://127.0.0.1:7687")
    monkeypatch.setenv("OPENSPG_NEO4J_USER", "neo4j")
    monkeypatch.setenv("OPENSPG_NEO4J_PASSWORD", "openspgneo4j")
    monkeypatch.setenv("OPENSPG_NEO4J_DATABASE", "neo4j")

    settings = Settings()

    assert settings.openspg_account == "openspg"
    assert settings.openspg_password == "openspg123"
    assert settings.openspg_project_name == "LabKAG"
    assert settings.openspg_namespace == "LabKAG"
    assert settings.openspg_write_backend == "neo4j"
    assert settings.openspg_neo4j_uri == "neo4j://127.0.0.1:7687"
    assert settings.openspg_neo4j_user == "neo4j"
    assert settings.openspg_neo4j_password == "openspgneo4j"
    assert settings.openspg_neo4j_database == "neo4j"


def test_openspg_client_uses_persistent_session_by_default():
    client = OpenSPGClient(mock=False)

    assert isinstance(client.session, requests.Session)


def test_openspg_client_lists_projects_after_login():
    session = FakeSession(
        [
            FakeResponse(status_code=200, payload={"success": True, "result": True}),
            FakeResponse(
                status_code=200,
                payload={
                    "success": True,
                    "result": {
                        "total": 1,
                        "pageSize": 10,
                        "pageNo": 1,
                        "records": [{"id": 12, "name": "LabKAG", "namespace": "LabKAG"}],
                    },
                },
            ),
        ]
    )
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        account="openspg",
        password="openspg123",
        mock=False,
        session=session,
    )

    result = client.list_projects()

    assert result["total"] == 1
    assert session.posts[0]["url"] == "https://openspg.example.com/v1/accounts/login"
    assert session.gets[0]["url"] == "https://openspg.example.com/v1/projects/list"
    assert session.gets[0]["params"] == {"page": 1, "size": 10}


def test_openspg_client_finds_project_by_name_from_records():
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                payload={
                    "success": True,
                    "result": {
                        "records": [
                            {"id": 1, "name": "Other", "namespace": "Other"},
                            {"id": 12, "name": "LabKAG", "namespace": "LabKAG"},
                        ]
                    },
                },
            )
        ]
    )
    client = OpenSPGClient(base_url="https://openspg.example.com", mock=False, session=session)

    project = client.find_project_by_name("LabKAG")

    assert project == {"id": 12, "name": "LabKAG", "namespace": "LabKAG"}


def test_openspg_client_finds_project_by_name_from_data():
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                payload={
                    "success": True,
                    "result": {
                        "data": [
                            {"id": 1, "name": "Other", "namespace": "Other"},
                            {"id": 12, "name": "LabKAG", "namespace": "LabKAG"},
                        ]
                    },
                },
            )
        ]
    )
    client = OpenSPGClient(base_url="https://openspg.example.com", mock=False, session=session)

    project = client.find_project_by_name("LabKAG")

    assert project == {"id": 12, "name": "LabKAG", "namespace": "LabKAG"}


def test_openspg_client_ensure_project_raises_when_missing():
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                payload={"success": True, "result": {"records": []}},
            )
        ]
    )
    client = OpenSPGClient(base_url="https://openspg.example.com", mock=False, session=session)

    with pytest.raises(OpenSPGClientError, match="OpenSPG project not found"):
        client.ensure_project("LabKAG")


def test_openspg_client_checks_configured_project_before_remote_write():
    session = FakeSession(
        [
            FakeResponse(status_code=200, payload={"success": True, "result": True}),
            FakeResponse(
                status_code=200,
                payload={
                    "success": True,
                    "result": {"records": [{"id": 12, "name": "LabKAG"}]},
                },
            ),
            FakeResponse(status_code=200, payload={"entities_created": 1}),
        ]
    )
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        write_path="/v1/not-yet-real-write",
        account="openspg",
        password="openspg123",
        project_name="LabKAG",
        mock=False,
        session=session,
    )

    client.write_graph({"entities": [{"id": "paper_001"}], "relations": []}, confirm=True)

    assert session.gets[0]["url"] == "https://openspg.example.com/v1/projects/list"
    assert session.posts[1]["url"] == "https://openspg.example.com/v1/not-yet-real-write"


def test_openspg_client_can_write_through_neo4j_backend():
    class FakeGraphStore:
        def __init__(self) -> None:
            self.calls = []

        def write_graph(self, graph_payload, *, project_id):
            self.calls.append({"graph_payload": graph_payload, "project_id": project_id})
            return {"entities_created": 1, "relations_created": 1, "evidence_created": 0}

    graph_store = FakeGraphStore()
    session = FakeSession(FakeResponse(status_code=200, payload={"success": True}))
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        write_backend="neo4j",
        project_id="labkag_demo",
        mock=False,
        graph_store=graph_store,
        session=session,
    )

    result = client.write_graph({"entities": [{"id": "paper_001"}], "relations": []}, confirm=True)

    assert result == {
        "paper_id": "paper_001",
        "entities_created": 1,
        "relations_created": 1,
        "evidence_created": 0,
        "dry_run": False,
        "mock": False,
    }
    assert graph_store.calls == [
        {
            "graph_payload": {"entities": [{"id": "paper_001"}], "relations": []},
            "project_id": "labkag_demo",
        }
    ]
    assert session.posts == []


def test_openspg_client_gets_config_by_id_and_version():
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                payload={
                    "success": True,
                    "result": {
                        "configId": "KAG_ENV",
                        "config": {"configTitle": {"graph_store": {"title": []}}},
                    },
                },
            )
        ]
    )
    client = OpenSPGClient(base_url="https://openspg.example.com", mock=False, session=session)

    config = client.get_config("KAG_ENV", version="1")

    assert config["configId"] == "KAG_ENV"
    assert session.gets[0]["url"] == "https://openspg.example.com/v1/configs/KAG_ENV/version/1"
    assert session.gets[0]["params"] == {"configId": "KAG_ENV", "version": "1"}


def test_openspg_client_gets_schema_script_by_project_id():
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                payload={"success": True, "result": "namespace LabKAG\n"},
            )
        ]
    )
    client = OpenSPGClient(base_url="https://openspg.example.com", mock=False, session=session)

    script = client.get_schema_script(project_id=1)

    assert script == "namespace LabKAG\n"
    assert session.gets[0]["url"] == "https://openspg.example.com/v1/schemas/getSchemaScript"
    assert session.gets[0]["params"] == {"projectId": 1}


def test_openspg_client_saves_schema_script():
    session = FakeSession([FakeResponse(status_code=200, payload={"success": True})])
    client = OpenSPGClient(base_url="https://openspg.example.com", mock=False, session=session)

    client.save_schema_script("namespace LabKAG\n")

    assert session.posts[0]["url"] == "https://openspg.example.com/v1/schemas"
    assert session.posts[0]["json"] == {"data": "namespace LabKAG\n"}


def test_openspg_client_applies_literature_schema_to_existing_script():
    session = FakeSession(
        [
            FakeResponse(
                status_code=200,
                payload={"success": True, "result": "namespace LabKAG\n"},
            ),
            FakeResponse(status_code=200, payload={"success": True}),
        ]
    )
    client = OpenSPGClient(
        base_url="https://openspg.example.com",
        project_id="1",
        namespace="LabKAG",
        mock=False,
        session=session,
    )

    result = client.apply_literature_schema()

    assert result["entity_types"] == [
        "Paper",
        "Method",
        "Material",
        "Condition",
        "Metric",
        "Result",
        "Conclusion",
        "Evidence",
    ]
    assert "Paper(论文): EntityType" in session.posts[0]["json"]["data"]
