from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "LabKAG"
    app_version: str = "0.1.0"
    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")
    parsed_dir: Path = Path("data/parsed")
    parsed_backup_dir: Path = Path("data/parsed_backup")
    extraction_dir: Path = Path("data/extractions")
    taxonomy_dir: Path = Path("data/taxonomies")
    graph_backend: str = "neo4j"
    neo4j_uri: str = "bolt://127.0.0.1:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = None
    neo4j_database: str = "neo4j"
    enable_embedding: bool = False
    embedding_api_key: str | None = None
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_timeout_seconds: int = 60
    llm_api_key: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 60
    mineru_api_token: str | None = None
    mineru_base_url: str = "https://mineru.net"
    mineru_language: str = "en"
    mineru_model_version: str = "vlm"
    mineru_enable_formula: bool = True
    mineru_enable_table: bool = True
    mineru_ocr: bool = False
    mineru_poll_interval_seconds: int = 5
    mineru_timeout_minutes: int = 30


settings = Settings()
