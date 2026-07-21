from pathlib import Path

import fitz
import pytest

from app.services.pdf_parser import parse_pdf


def test_parse_pdf_extracts_text_pages(tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "LabKAG parser test")
    document.save(pdf_path)
    document.close()

    parsed = parse_pdf(pdf_path, document_id="doc_001")

    assert parsed.document_id == "doc_001"
    assert parsed.pages[0].page == 1
    assert "LabKAG parser test" in parsed.pages[0].text


def test_parse_pdf_raises_file_not_found_for_missing_path(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        parse_pdf(tmp_path / "missing.pdf", document_id="doc_missing")


def test_parse_pdf_passes_mineru_output_dir_override_to_client(tmp_path: Path, monkeypatch):
    from dataclasses import dataclass

    pdf_path = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "LabKAG parser test")
    document.save(pdf_path)
    document.close()

    @dataclass
    class FakeArtifacts:
        markdown: str

    class FakeMinerUClient:
        def __init__(self):
            self.materialize_calls = []

        def materialize(self, pdf_path, output_dir, slug_source=None):
            self.materialize_calls.append(output_dir)
            return FakeArtifacts(markdown="# Title\n\n" + ("x" * 250))

    fake_client = FakeMinerUClient()
    monkeypatch.setattr(
        "app.adapters.mineru_client.configured_mineru_client", lambda: fake_client
    )
    custom_dir = tmp_path / "custom_mineru_output"

    parsed = parse_pdf(pdf_path, document_id="doc_001", mineru_output_dir=custom_dir)

    assert fake_client.materialize_calls == [custom_dir]
    assert parsed.title == "Title"


def test_parse_pdf_uses_default_parsed_dir_when_no_override_given(tmp_path: Path, monkeypatch):
    from dataclasses import dataclass

    from app.config import settings

    pdf_path = tmp_path / "paper.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "LabKAG parser test")
    document.save(pdf_path)
    document.close()

    @dataclass
    class FakeArtifacts:
        markdown: str

    class FakeMinerUClient:
        def __init__(self):
            self.materialize_calls = []

        def materialize(self, pdf_path, output_dir, slug_source=None):
            self.materialize_calls.append(output_dir)
            return FakeArtifacts(markdown="# Title\n\n" + ("x" * 250))

    fake_client = FakeMinerUClient()
    monkeypatch.setattr(
        "app.adapters.mineru_client.configured_mineru_client", lambda: fake_client
    )

    parse_pdf(pdf_path, document_id="doc_001")

    assert fake_client.materialize_calls == [Path(settings.parsed_dir)]


def test_parse_pdf_passes_original_file_name_as_slug_source(tmp_path: Path, monkeypatch):
    from dataclasses import dataclass

    # The local path is an internal storage path (e.g. data/uploads/{file_id}.pdf)
    # that deliberately does not match the paper's real filename, to prove the
    # slug is computed from original_file_name, not from pdf_path.
    pdf_path = tmp_path / "file_abc123.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "LabKAG parser test")
    document.save(pdf_path)
    document.close()

    @dataclass
    class FakeArtifacts:
        markdown: str

    class FakeMinerUClient:
        def __init__(self):
            self.materialize_calls = []

        def materialize(self, pdf_path, output_dir, slug_source=None):
            self.materialize_calls.append(slug_source)
            return FakeArtifacts(markdown="# Title\n\n" + ("x" * 250))

    fake_client = FakeMinerUClient()
    monkeypatch.setattr(
        "app.adapters.mineru_client.configured_mineru_client", lambda: fake_client
    )

    parse_pdf(
        pdf_path,
        document_id="doc_001",
        original_file_name="1-s2.0-S0040402013011022-main.pdf",
    )

    assert fake_client.materialize_calls == ["1-s2.0-S0040402013011022-main.pdf"]
