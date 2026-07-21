from pathlib import Path

from app.storage.taxonomy_store import TaxonomyStore


def test_save_and_load_taxonomy_roundtrip(tmp_path: Path):
    store = TaxonomyStore(taxonomy_dir=tmp_path / "taxonomies")

    store.save_taxonomy("proj_1", {"project_id": "proj_1", "categories": [], "version": 1})
    loaded = store.load_taxonomy("proj_1")

    assert loaded == {"project_id": "proj_1", "categories": [], "version": 1}


def test_load_taxonomy_returns_none_when_missing(tmp_path: Path):
    store = TaxonomyStore(taxonomy_dir=tmp_path / "taxonomies")

    assert store.load_taxonomy("does_not_exist") is None


def test_save_taxonomy_overwrites_existing_file(tmp_path: Path):
    store = TaxonomyStore(taxonomy_dir=tmp_path / "taxonomies")

    store.save_taxonomy("proj_1", {"project_id": "proj_1", "categories": [], "version": 1})
    store.save_taxonomy("proj_1", {"project_id": "proj_1", "categories": [], "version": 2})

    assert store.load_taxonomy("proj_1")["version"] == 2
