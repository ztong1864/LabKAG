import pytest

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
