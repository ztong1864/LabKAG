from __future__ import annotations

import json
import re
from pathlib import Path

from app.schemas.document import DocumentPage, ParsedDocument

# MinerU output is considered empty if shorter than this (likely a parsing failure)
_MINERU_MIN_CHARS = 200


def parse_pdf(
    path: Path | str,
    document_id: str,
    use_backup: bool = False,
    mineru_output_dir: Path | str | None = None,
    original_file_name: str | None = None,
) -> ParsedDocument:
    """Parse a PDF using MinerU (if configured) with PyMuPDF fallback.

    When MinerU returns empty or very short content, falls back to PyMuPDF
    and saves the result to parsed_backup_dir for later use.

    If use_backup=True, reads directly from parsed_backup_dir (PyMuPDF output)
    without calling MinerU.

    mineru_output_dir overrides settings.parsed_dir for this call only, so
    different projects/batches can target different MinerU output locations
    without restarting the server.

    original_file_name, if given, is used to compute the MinerU cache slug
    instead of `path`'s own filename -- `path` is often an internal storage
    path (e.g. data/uploads/{file_id}.pdf) that doesn't match the slug a
    pre-parsed batch (e.g. from mineru_batch_parse.py) used, which is keyed
    on the paper's real filename.
    """
    pdf_path = Path(path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    from app.config import settings

    if use_backup:
        return _load_or_parse_backup(pdf_path, document_id, settings.parsed_backup_dir)

    from app.adapters.mineru_client import MinerUError, configured_mineru_client
    client = configured_mineru_client()
    if client is not None:
        try:
            output_dir = (
                Path(mineru_output_dir) if mineru_output_dir else Path(settings.parsed_dir)
            )
            artifacts = client.materialize(pdf_path, output_dir, slug_source=original_file_name)
            if len(artifacts.markdown.strip()) >= _MINERU_MIN_CHARS:
                return _document_from_markdown(artifacts.markdown, document_id, pdf_path.name)
            # MinerU returned too little — fall through to PyMuPDF backup
        except MinerUError:
            raise
        except Exception as exc:
            raise RuntimeError(f"MinerU parsing failed: {exc}") from exc

    return _load_or_parse_backup(pdf_path, document_id, Path(settings.parsed_backup_dir))


def _load_or_parse_backup(pdf_path: Path, document_id: str, backup_dir: Path) -> ParsedDocument:
    """Load PyMuPDF result from backup dir if it exists, otherwise parse and save it."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    cache_file = backup_dir / f"{pdf_path.stem}.json"

    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        return ParsedDocument.model_validate(data)

    doc = _parse_with_pymupdf(pdf_path, document_id)
    cache_file.write_text(
        json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return doc


def _parse_with_pymupdf(pdf_path: Path, document_id: str) -> ParsedDocument:
    import fitz
    pages: list[DocumentPage] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            pages.append(DocumentPage(page=index, text=page.get_text("text").strip()))
    return ParsedDocument(document_id=document_id, file_name=pdf_path.name, pages=pages)


def _document_from_markdown(markdown: str, document_id: str, file_name: str) -> ParsedDocument:
    sections = _split_markdown_sections(markdown)
    pages = [
        DocumentPage(page=i, text=section.strip())
        for i, section in enumerate(sections, start=1)
        if section.strip()
    ]
    if not pages:
        pages = [DocumentPage(page=1, text=markdown.strip())]
    return ParsedDocument(
        document_id=document_id,
        file_name=file_name,
        title=_extract_title(markdown),
        pages=pages,
    )


def _split_markdown_sections(markdown: str) -> list[str]:
    if "<!-- PAGE BREAK -->" in markdown:
        return markdown.split("<!-- PAGE BREAK -->")
    if "\n---\n" in markdown and markdown.count("\n---\n") > 2:
        return markdown.split("\n---\n")
    parts = re.split(r"(?=\n#{1,2} )", markdown)
    if len(parts) <= 2:
        size = 3000
        return [markdown[i: i + size] for i in range(0, len(markdown), size)]
    return parts


def _extract_title(markdown: str) -> str:
    match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    return match.group(1).strip() if match else ""
