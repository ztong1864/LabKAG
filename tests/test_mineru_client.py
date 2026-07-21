import shutil
import zipfile
from pathlib import Path

import pytest
import requests

from app.adapters.mineru_client import MIN_MARKDOWN_CHARS, MinerUClient, _with_retries


class FakeMinerUClient(MinerUClient):
    def __init__(self, zip_source: Path | None = None) -> None:
        super().__init__(token="test-token")
        self.zip_source = zip_source
        self.upload_calls: list[tuple[Path, str]] = []

    def _upload_and_poll(self, session, pdf_path: Path, data_id: str) -> str:
        self.upload_calls.append((pdf_path, data_id))
        return "https://example.test/mineru.zip"

    def _download_binary(self, url: str, dest: Path) -> None:
        if self.zip_source is None:
            raise AssertionError("Unexpected download for cached MinerU result.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.zip_source, dest)


def _write_result_zip(path: Path, markdown: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("full.md", markdown)


def test_materialize_reuses_cached_markdown_when_cache_is_long_enough(tmp_path: Path):
    output_dir = tmp_path / "mineru"
    markdown_path = output_dir / "markdown" / "paper.md"
    cached_markdown = "x" * MIN_MARKDOWN_CHARS
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(cached_markdown, encoding="utf-8")

    client = FakeMinerUClient()
    artifacts = client.materialize(tmp_path / "paper.pdf", output_dir)

    assert artifacts.markdown == cached_markdown
    assert client.upload_calls == []


def test_materialize_retries_mineru_when_cached_markdown_is_too_short(tmp_path: Path):
    output_dir = tmp_path / "mineru"
    markdown_path = output_dir / "markdown" / "paper.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text("too short", encoding="utf-8")

    fresh_markdown = "fresh MinerU markdown " + ("x" * MIN_MARKDOWN_CHARS)
    zip_path = tmp_path / "result.zip"
    _write_result_zip(zip_path, fresh_markdown)

    client = FakeMinerUClient(zip_source=zip_path)
    artifacts = client.materialize(tmp_path / "paper.pdf", output_dir)

    assert len(client.upload_calls) == 1
    assert artifacts.markdown == fresh_markdown
    assert markdown_path.read_text(encoding="utf-8") == fresh_markdown


def test_materialize_uses_slug_source_for_cache_lookup_instead_of_local_path(tmp_path: Path):
    output_dir = tmp_path / "mineru"
    # Cache written under the paper's real name, as mineru_batch_parse.py would.
    cached_markdown = "x" * MIN_MARKDOWN_CHARS
    markdown_path = output_dir / "markdown" / "1-s2.0-s0040402013011022-main.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(cached_markdown, encoding="utf-8")

    client = FakeMinerUClient()
    # Local file lives under an internal id-based name that would slugify
    # completely differently -- without slug_source this must miss the cache.
    local_path = tmp_path / "file_abc123.pdf"

    artifacts = client.materialize(
        local_path,
        output_dir,
        slug_source="1-s2.0-S0040402013011022-main.pdf",
    )

    assert artifacts.markdown == cached_markdown
    assert client.upload_calls == []


def test_materialize_without_slug_source_misses_cache_keyed_on_original_name(tmp_path: Path):
    output_dir = tmp_path / "mineru"
    cached_markdown = "x" * MIN_MARKDOWN_CHARS
    markdown_path = output_dir / "markdown" / "1-s2.0-s0040402013011022-main.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(cached_markdown, encoding="utf-8")

    fresh_markdown = "fresh MinerU markdown " + ("x" * MIN_MARKDOWN_CHARS)
    zip_path = tmp_path / "result.zip"
    _write_result_zip(zip_path, fresh_markdown)
    client = FakeMinerUClient(zip_source=zip_path)
    local_path = tmp_path / "file_abc123.pdf"

    artifacts = client.materialize(local_path, output_dir)

    assert artifacts.markdown == fresh_markdown
    assert len(client.upload_calls) == 1


def test_with_retries_returns_immediately_on_success():
    calls = []

    def succeed():
        calls.append(1)
        return "ok"

    assert _with_retries(succeed) == "ok"
    assert len(calls) == 1


def test_with_retries_recovers_after_transient_connection_error(monkeypatch):
    monkeypatch.setattr("app.adapters.mineru_client.time.sleep", lambda _: None)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise requests.exceptions.ConnectionError("dropped")
        return "recovered"

    assert _with_retries(flaky) == "recovered"
    assert len(attempts) == 3


def test_with_retries_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr("app.adapters.mineru_client.time.sleep", lambda _: None)
    attempts = []

    def always_fails():
        attempts.append(1)
        raise requests.exceptions.ConnectionError("still down")

    with pytest.raises(requests.exceptions.ConnectionError, match="still down"):
        _with_retries(always_fails)
    assert len(attempts) == 3


def test_download_binary_retries_on_transient_connection_error(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.adapters.mineru_client.time.sleep", lambda _: None)
    call_count = {"n": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"zip-bytes"

    def fake_get(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise requests.exceptions.ConnectionError("dropped mid-download")
        return FakeResponse()

    monkeypatch.setattr("app.adapters.mineru_client.requests.get", fake_get)
    dest = tmp_path / "out.zip"

    MinerUClient._download_binary("https://example.test/file.zip", dest)

    assert call_count["n"] == 2
    assert dest.read_bytes() == b"zip-bytes"
