import json
from pathlib import Path
from typing import Any

from app.config import settings


class TaxonomyStore:
    def __init__(self, taxonomy_dir: Path | None = None) -> None:
        self.taxonomy_dir = taxonomy_dir or settings.taxonomy_dir

    def save_taxonomy(self, project_id: str, payload: dict[str, Any]) -> Path:
        self.taxonomy_dir.mkdir(parents=True, exist_ok=True)
        path = self.taxonomy_dir / f"{project_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_taxonomy(self, project_id: str) -> dict[str, Any] | None:
        path = self.taxonomy_dir / f"{project_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


taxonomy_store = TaxonomyStore()
