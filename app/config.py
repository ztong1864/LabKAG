from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LabKAG"
    app_version: str = "0.1.0"
    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")
    parsed_dir: Path = Path("data/parsed")
    extraction_dir: Path = Path("data/extractions")
    mock_kag: bool = True
    openspg_base_url: str | None = None
    openspg_write_path: str = "/api/graph/write"
    openspg_api_key: str | None = None
    openspg_account: str | None = None
    openspg_password: str | None = None
    openspg_project_id: str | None = None
    openspg_project_name: str | None = None
    openspg_namespace: str | None = None
    openspg_timeout_seconds: int = 30
    openspg_write_backend: str = "http"
    openspg_neo4j_uri: str = "neo4j://127.0.0.1:7687"
    openspg_neo4j_user: str = "neo4j"
    openspg_neo4j_password: str | None = None
    openspg_neo4j_database: str = "neo4j"
    allow_mock_extractor: bool = True
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 60


settings = Settings()
