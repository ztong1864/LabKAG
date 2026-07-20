from __future__ import annotations

import re

from app.schemas.document import DocumentChunk, DocumentPage


def chunk_pages(
    document_id: str,
    pages: list[DocumentPage],
    max_chars: int = 1800,
) -> list[DocumentChunk]:
    """Chunk document pages into evidence-ready chunks.

    For MinerU Markdown pages (sections), splits on paragraph/table boundaries
    to avoid cutting mid-sentence. For plain PyMuPDF text, splits on max_chars.
    """
    chunks: list[DocumentChunk] = []
    counter = 1
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        segments = _split_page(text, max_chars)
        for segment in segments:
            if not segment.strip():
                continue
            chunks.append(
                DocumentChunk(
                    document_id=document_id,
                    chunk_id=f"{document_id}_chunk_{counter:03d}",
                    page=page.page,
                    section_title=_section_title(segment),
                    text=segment.strip(),
                )
            )
            counter += 1
    return chunks


def _split_page(text: str, max_chars: int) -> list[str]:
    """Split text at natural boundaries (paragraphs, table rows) respecting max_chars."""
    if len(text) <= max_chars:
        return [text]

    # Detect if this is Markdown (MinerU output has | for tables, ## headings)
    if _is_markdown(text):
        return _split_markdown(text, max_chars)

    # Plain text: split on character boundary
    return [text[i: i + max_chars] for i in range(0, len(text), max_chars)]


def _is_markdown(text: str) -> bool:
    return bool(re.search(r"^#{1,3} |^\|.+\|", text, re.MULTILINE))


def _split_markdown(text: str, max_chars: int) -> list[str]:
    """Split Markdown at paragraph/table block boundaries."""
    # Split into blocks separated by blank lines
    blocks = re.split(r"\n{2,}", text)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for block in blocks:
        block_len = len(block)
        if current_len + block_len > max_chars and current:
            chunks.append("\n\n".join(current))
            current = [block]
            current_len = block_len
        else:
            current.append(block)
            current_len += block_len + 2  # +2 for the blank line separator

    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _section_title(text: str) -> str | None:
    # Prefer Markdown heading
    heading = re.match(r"^#{1,3}\s+(.+)$", text, re.MULTILINE)
    if heading:
        return heading.group(1).strip()[:80]
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:80] if first_line else None
