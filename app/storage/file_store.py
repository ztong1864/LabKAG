import json
from pathlib import Path

from app.config import settings
from app.utils.ids import new_id


class UnsupportedFileTypeError(ValueError):
    pass


class FileStore:
    def __init__(self, upload_dir: Path | None = None) -> None:
        self.upload_dir = upload_dir or settings.upload_dir

    def save_upload(self, file_name: str, content: bytes) -> dict[str, str]:
        if not file_name.lower().endswith(".pdf"):
            raise UnsupportedFileTypeError("Only PDF files are supported.")

        self.upload_dir.mkdir(parents=True, exist_ok=True)
        file_id = new_id("file")
        stored_name = f"{file_id}.pdf"
        stored_path = self.upload_dir / stored_name
        stored_path.write_bytes(content)
        self._meta_path(file_id).write_text(
            json.dumps({"file_name": file_name}, ensure_ascii=False), encoding="utf-8"
        )

        return {
            "file_id": file_id,
            "file_name": file_name,
            "stored_path": str(stored_path),
        }

    def resolve(self, file_id: str) -> Path:
        path = self.upload_dir / f"{file_id}.pdf"
        if not path.exists():
            raise FileNotFoundError(f"File {file_id} was not found.")
        return path

    def original_name(self, file_id: str) -> str | None:
        """The filename the caller uploaded under, if still on record. Used so
        MinerU output can be cache-keyed on the paper's real name rather than
        its internal file_id -- lets a pre-parsed batch (e.g. from
        mineru_batch_parse.py, keyed by original filename) be reused during
        /v1/papers/extract instead of silently re-parsing."""
        meta_path = self._meta_path(file_id)
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return data.get("file_name")

    def _meta_path(self, file_id: str) -> Path:
        return self.upload_dir / f"{file_id}.meta.json"


file_store = FileStore()
