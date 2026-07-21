from pathlib import Path

import pytest

from app.storage.file_store import FileStore, UnsupportedFileTypeError


def test_save_upload_persists_and_returns_original_name(tmp_path: Path):
    store = FileStore(upload_dir=tmp_path)

    result = store.save_upload("1-s2.0-S0040402013011022-main.pdf", b"%PDF-1.4 fake content")

    assert result["file_name"] == "1-s2.0-S0040402013011022-main.pdf"
    assert store.original_name(result["file_id"]) == "1-s2.0-S0040402013011022-main.pdf"


def test_original_name_returns_none_for_unknown_file_id(tmp_path: Path):
    store = FileStore(upload_dir=tmp_path)

    assert store.original_name("file_does_not_exist") is None


def test_resolve_returns_stored_path_not_original_name(tmp_path: Path):
    store = FileStore(upload_dir=tmp_path)

    result = store.save_upload("paper.pdf", b"%PDF-1.4 fake content")
    resolved = store.resolve(result["file_id"])

    assert resolved.name == f"{result['file_id']}.pdf"
    assert resolved.read_bytes() == b"%PDF-1.4 fake content"


def test_save_upload_rejects_non_pdf(tmp_path: Path):
    store = FileStore(upload_dir=tmp_path)

    with pytest.raises(UnsupportedFileTypeError):
        store.save_upload("notes.txt", b"plain text")
