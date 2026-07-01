import hashlib
from typing import Any

import requests

from app.adapters.labkag_schema import build_literature_schema_script, literature_entity_names
from app.adapters.neo4j_graph_store import Neo4jGraphStore
from app.config import settings


class OpenSPGClientError(RuntimeError):
    pass


class OpenSPGClient:
    def __init__(
        self,
        base_url: str | None = None,
        write_path: str | None = None,
        api_key: str | None = None,
        account: str | None = None,
        password: str | None = None,
        project_id: str | None = None,
        project_name: str | None = None,
        namespace: str | None = None,
        timeout_seconds: int | None = None,
        write_backend: str | None = None,
        graph_store: Any | None = None,
        mock: bool | None = None,
        session: Any | None = None,
    ) -> None:
        self.base_url = (base_url or settings.openspg_base_url or "").rstrip("/")
        self.write_path = write_path or settings.openspg_write_path
        self.api_key = api_key if api_key is not None else settings.openspg_api_key
        self.account = account if account is not None else settings.openspg_account
        self.password = password if password is not None else settings.openspg_password
        self.project_id = project_id if project_id is not None else settings.openspg_project_id
        self.project_name = (
            project_name if project_name is not None else settings.openspg_project_name
        )
        self.namespace = namespace if namespace is not None else settings.openspg_namespace
        self.timeout_seconds = timeout_seconds or settings.openspg_timeout_seconds
        self.write_backend = write_backend or settings.openspg_write_backend
        self.graph_store = graph_store
        self.mock = settings.mock_kag if mock is None else mock
        self.session = session or requests.Session()
        self._logged_in = False

    def write_graph(self, graph_payload: dict, confirm: bool = False) -> dict:
        if self.mock or not confirm:
            return self._mock_result(graph_payload, confirm=confirm)

        if not self.base_url:
            raise OpenSPGClientError("OPENSPG_BASE_URL is required when MOCK_KAG=false.")

        self._ensure_login()
        if self.project_name:
            self.ensure_project(self.project_name)

        if self.write_backend == "neo4j":
            payload = self._neo4j_graph_store().write_graph(
                graph_payload,
                project_id=self.project_id or self.project_name,
            )
            return self._write_result(graph_payload, payload)

        response = self.session.post(
            f"{self.base_url}{self.write_path}",
            headers=self._headers(),
            json=graph_payload,
            timeout=self.timeout_seconds,
        )
        payload = self._handle_response(response, operation="write")
        return self._write_result(graph_payload, payload)

    @staticmethod
    def _write_result(graph_payload: dict, payload: dict) -> dict:
        return {
            "paper_id": payload.get("paper_id")
            or OpenSPGClient._paper_id_from_payload(graph_payload),
            "entities_created": payload.get("entities_created", 0),
            "relations_created": payload.get("relations_created", 0),
            "evidence_created": payload.get("evidence_created", 0),
            "dry_run": False,
            "mock": False,
        }

    @staticmethod
    def _paper_id_from_payload(graph_payload: dict) -> str:
        for entity in graph_payload.get("entities", []):
            if entity.get("type") == "Paper":
                return entity.get("id", "paper_001")
        return "paper_001"

    def _neo4j_graph_store(self) -> Any:
        if self.graph_store is not None:
            return self.graph_store
        if not settings.openspg_neo4j_password:
            raise OpenSPGClientError(
                "OPENSPG_NEO4J_PASSWORD is required when OPENSPG_WRITE_BACKEND=neo4j."
            )
        self.graph_store = Neo4jGraphStore(
            uri=settings.openspg_neo4j_uri,
            user=settings.openspg_neo4j_user,
            password=settings.openspg_neo4j_password,
            database=settings.openspg_neo4j_database,
        )
        return self.graph_store

    def list_projects(self, page: int = 1, size: int = 10) -> dict:
        if not self.base_url:
            raise OpenSPGClientError("OPENSPG_BASE_URL is required when MOCK_KAG=false.")

        self._ensure_login()
        response = self.session.get(
            f"{self.base_url}/v1/projects/list",
            headers=self._headers(),
            params={"page": page, "size": size},
            timeout=self.timeout_seconds,
        )
        payload = self._handle_response(response, operation="list projects")
        return payload.get("result", payload)

    def find_project_by_name(self, name: str) -> dict | None:
        result = self.list_projects()
        projects = result.get("records") or result.get("data") or []
        for project in projects:
            if project.get("name") == name:
                return project
        return None

    def ensure_project(self, name: str) -> dict:
        project = self.find_project_by_name(name)
        if project is None:
            raise OpenSPGClientError(
                f"OpenSPG project not found: {name}. Create it in OpenSPG before real writes."
            )
        return project

    def get_config(self, config_id: str, version: str = "1") -> dict:
        if not self.base_url:
            raise OpenSPGClientError("OPENSPG_BASE_URL is required when MOCK_KAG=false.")

        self._ensure_login()
        response = self.session.get(
            f"{self.base_url}/v1/configs/{config_id}/version/{version}",
            headers=self._headers(),
            params={"configId": config_id, "version": version},
            timeout=self.timeout_seconds,
        )
        payload = self._handle_response(response, operation="get config")
        return payload.get("result", payload)

    def get_schema_script(self, project_id: int | str | None = None) -> str:
        if not self.base_url:
            raise OpenSPGClientError("OPENSPG_BASE_URL is required when MOCK_KAG=false.")

        effective_project_id = project_id or self.project_id
        if effective_project_id is None:
            raise OpenSPGClientError("OPENSPG_PROJECT_ID is required to read schema script.")

        self._ensure_login()
        response = self.session.get(
            f"{self.base_url}/v1/schemas/getSchemaScript",
            headers=self._headers(),
            params={"projectId": int(effective_project_id)},
            timeout=self.timeout_seconds,
        )
        payload = self._handle_response(response, operation="get schema script")
        result = payload.get("result", "")
        if not isinstance(result, str):
            raise OpenSPGClientError("OpenSPG get schema script returned a non-string result.")
        return result

    def save_schema_script(self, schema_script: str) -> dict:
        if not self.base_url:
            raise OpenSPGClientError("OPENSPG_BASE_URL is required when MOCK_KAG=false.")

        self._ensure_login()
        response = self.session.post(
            f"{self.base_url}/v1/schemas",
            headers=self._headers(),
            json={"data": schema_script},
            timeout=self.timeout_seconds,
        )
        return self._handle_response(response, operation="save schema script")

    def apply_literature_schema(self) -> dict:
        if self.project_name:
            self.ensure_project(self.project_name)
        current_script = self.get_schema_script()
        schema_script = build_literature_schema_script(
            current_script,
            namespace=self.namespace or self.project_name or "LabKAG",
        )
        self.save_schema_script(schema_script)
        return {
            "project_id": self.project_id,
            "namespace": self.namespace or self.project_name or "LabKAG",
            "entity_types": literature_entity_names(),
        }

    def _ensure_login(self) -> None:
        if self._logged_in or not self.account or not self.password:
            return

        response = self.session.post(
            f"{self.base_url}/v1/accounts/login",
            headers=self._headers(),
            json={
                "account": self.account,
                "password": self._openspg_password_hash(self.password),
            },
            timeout=self.timeout_seconds,
        )
        self._handle_response(response, operation="login")
        self._logged_in = True

    @staticmethod
    def _handle_response(response: Any, operation: str) -> dict:
        if response.status_code >= 400:
            detail = response.text or ""
            raise OpenSPGClientError(
                f"OpenSPG {operation} failed with HTTP {response.status_code}: {detail}".strip()
            )

        payload = response.json()
        if payload.get("success") is False:
            error_code = payload.get("errorCode", "unknown_error")
            message = (
                payload.get("errorMsg")
                or payload.get("errorMessage")
                or payload.get("message")
                or payload.get("url")
                or ""
            )
            raise OpenSPGClientError(
                f"OpenSPG {operation} failed with business error {error_code}: {message}".strip()
            )
        return payload

    @staticmethod
    def _openspg_password_hash(password: str) -> str:
        return hashlib.sha256(f"{password}OPENSPG".encode()).hexdigest()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.project_id:
            headers["X-OpenSPG-Project"] = self.project_id
        return headers

    def _mock_result(self, graph_payload: dict, confirm: bool = False) -> dict:
        return {
            "paper_id": "paper_001",
            "entities_created": len(graph_payload.get("entities", [])) if confirm else 0,
            "relations_created": len(graph_payload.get("relations", [])) if confirm else 0,
            "evidence_created": len(
                [
                    entity
                    for entity in graph_payload.get("entities", [])
                    if entity.get("type") == "Evidence"
                ]
            )
            if confirm
            else 0,
            "dry_run": not confirm,
            "mock": self.mock,
        }


openspg_client = OpenSPGClient()
