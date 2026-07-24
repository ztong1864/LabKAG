import pytest

from app.config import settings
from app.storage.file_store import file_store
from app.storage.metadata_store import metadata_store
from app.storage.taxonomy_store import taxonomy_store


@pytest.fixture(autouse=True)
def isolate_disk_stores(tmp_path, monkeypatch):
    """Redirect the shared file_store/metadata_store/taxonomy_store singletons
    to a per-test temp directory so tests never read or write real data/
    state and can't leak paper_id/document_id/project_id collisions into
    each other."""
    monkeypatch.setattr(file_store, "upload_dir", tmp_path / "uploads")
    monkeypatch.setattr(metadata_store, "metadata_dir", tmp_path / "metadata")
    monkeypatch.setattr(taxonomy_store, "taxonomy_dir", tmp_path / "taxonomies")


@pytest.fixture(autouse=True)
def isolate_external_credentials(monkeypatch):
    """Clear API tokens read from a local .env before each test.

    configured_mineru_client()/configured_chat_client()/configured_embedding_client()
    all gate on these settings being set. Tests that exercise the "no
    provider configured" path, or that want a real client, explicitly
    monkeypatch the configured_*_client function itself -- that always wins
    over this fixture since it patches a different target. Without this,
    whether a test hits a real network call (and how slowly it fails/falls
    back) depends on whatever happens to be in a developer's local .env,
    which is exactly the kind of ambient-state dependency the disk-store
    isolation above already guards against for storage.
    """
    monkeypatch.setattr(settings, "mineru_api_token", None)
    monkeypatch.setattr(settings, "llm_api_key", None)
    monkeypatch.setattr(settings, "embedding_api_key", None)
