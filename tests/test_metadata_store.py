from pathlib import Path

from app.storage.metadata_store import MetadataStore


def test_save_extraction_writes_to_metadata_dir(tmp_path: Path):
    store = MetadataStore(metadata_dir=tmp_path / "metadata")

    store.save_extraction("doc_001", {"paper": {"paper_id": "paper_001"}})

    assert (tmp_path / "metadata" / "doc_001.json").exists()
    assert store.load_extraction("doc_001") == {"paper": {"paper_id": "paper_001"}}


def test_save_extraction_also_writes_extra_output_dir_copy(tmp_path: Path):
    store = MetadataStore(metadata_dir=tmp_path / "metadata")
    extra_dir = tmp_path / "output_llm"

    store.save_extraction(
        "doc_001", {"paper": {"paper_id": "paper_001"}}, extra_output_dir=extra_dir
    )

    assert (tmp_path / "metadata" / "doc_001.json").exists()
    assert (extra_dir / "doc_001.json").exists()
    import json

    assert json.loads((extra_dir / "doc_001.json").read_text(encoding="utf-8")) == {
        "paper": {"paper_id": "paper_001"}
    }


def test_save_extraction_without_extra_output_dir_only_writes_canonical_copy(tmp_path: Path):
    store = MetadataStore(metadata_dir=tmp_path / "metadata")

    store.save_extraction("doc_001", {"paper": {}})

    assert list((tmp_path / "metadata").glob("*.json")) == [tmp_path / "metadata" / "doc_001.json"]


def test_load_extraction_returns_none_when_missing(tmp_path: Path):
    store = MetadataStore(metadata_dir=tmp_path / "metadata")

    assert store.load_extraction("does_not_exist") is None


def test_load_extraction_by_paper_id_finds_matching_paper(tmp_path: Path):
    store = MetadataStore(metadata_dir=tmp_path / "metadata")
    store.save_extraction("doc_001", {"paper": {"paper_id": "paper_001"}})
    store.save_extraction("doc_002", {"paper": {"paper_id": "paper_002"}})

    found = store.load_extraction_by_paper_id("paper_002")

    assert found == {"paper": {"paper_id": "paper_002"}}
