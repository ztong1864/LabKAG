import shutil
import zipfile
from pathlib import Path

from app.adapters.mineru_client import MIN_MARKDOWN_CHARS, MinerUClient


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
