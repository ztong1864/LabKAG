import json
from pathlib import Path
from typing import Any

from app.config import settings


class MetadataStore:
    def __init__(self, metadata_dir: Path | None = None) -> None:
        self.metadata_dir = metadata_dir or settings.metadata_dir

    def save_extraction(
        self,
        document_id: str,
        payload: dict[str, Any],
        extra_output_dir: Path | str | None = None,
    ) -> Path:
        """Always writes to metadata_dir (the canonical location every read
        path -- /v1/papers/{id}/knowledge, ingest re-reads, backfill,
        taxonomy bootstrap -- depends on). extra_output_dir, if given,
        additionally writes an identical copy there for external visibility
        (e.g. a custom folder outside data/), without changing where the
        canonical copy lives."""
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        path = self.metadata_dir / f"{document_id}.json"
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")

        if extra_output_dir:
            extra_dir = Path(extra_output_dir)
            extra_dir.mkdir(parents=True, exist_ok=True)
            (extra_dir / f"{document_id}.json").write_text(text, encoding="utf-8")

        return path

    def load_extraction(self, document_id: str) -> dict[str, Any] | None:
        path = self.metadata_dir / f"{document_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_extraction_by_paper_id(self, paper_id: str) -> dict[str, Any] | None:
        if not self.metadata_dir.exists():
            return None
        for path in self.metadata_dir.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            paper = payload.get("paper") or {}
            if paper.get("paper_id") == paper_id:
                return payload
        return None


metadata_store = MetadataStore()
