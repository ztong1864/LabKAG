from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

SUCCESS_STATES = {"done", "success", "finished", "completed"}
FAILURE_STATES = {"failed", "error"}
TERMINAL_STATES = SUCCESS_STATES | FAILURE_STATES
MIN_MARKDOWN_CHARS = 200


class MinerUError(RuntimeError):
    pass


@dataclass
class MinerUArtifacts:
    """Paths to all files produced by a full MinerU materialize."""
    slug: str
    raw_zip: Path
    extracted_dir: Path
    full_md: Path
    markdown_copy: Path
    markdown: str = field(repr=False)


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._/-]+", "-", ascii_text).strip("-._/")
    cleaned = cleaned.replace("/", "__")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.lower() or "document"


def _rewrite_image_paths(markdown: str, slug: str) -> str:
    text = markdown
    text = text.replace("(images/", f"(../extracted/{slug}/images/")
    text = text.replace('src="images/', f'src="../extracted/{slug}/images/')
    text = text.replace("src='images/", f"src='../extracted/{slug}/images/")
    return text


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class MinerUClient:
    def __init__(
        self,
        token: str,
        base_url: str = "https://mineru.net",
        language: str = "en",
        model_version: str = "vlm",
        enable_formula: bool = True,
        enable_table: bool = True,
        ocr: bool = False,
        poll_interval_seconds: int = 5,
        timeout_minutes: int = 30,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.language = language
        self.model_version = model_version
        self.enable_formula = enable_formula
        self.enable_table = enable_table
        self.ocr = ocr
        self.poll_interval = poll_interval_seconds
        self.timeout_seconds = timeout_minutes * 60

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _post(self, session: requests.Session, path: str, payload: dict) -> dict:
        response = session.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise MinerUError(f"MinerU API error at {path}: {data.get('msg') or data}")
        return data

    def _get(self, session: requests.Session, path: str) -> dict:
        response = session.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise MinerUError(f"MinerU API error at {path}: {data.get('msg') or data}")
        return data

    def parse_pdf(self, pdf_path: Path) -> str:
        """Upload PDF to MinerU, wait, return Markdown string only (no artifacts saved)."""
        session = requests.Session()
        try:
            zip_url = self._upload_and_poll(session, pdf_path, f"labkag-{pdf_path.stem[:60]}")
            with tempfile.TemporaryDirectory() as tmpdir:
                return self._extract_markdown_from_zip(zip_url, Path(tmpdir))
        finally:
            session.close()

    def materialize(self, pdf_path: Path, output_dir: Path, force: bool = False) -> MinerUArtifacts:
        """Full materialize: save zip, extract all sidecars, images, and rewritten markdown."""
        slug = _slugify(pdf_path.stem)
        data_id = f"labkag-{slug}"[:96]

        raw_zip = output_dir / "raw_zips" / f"{slug}.zip"
        extracted_dir = output_dir / "extracted" / slug
        markdown_path = output_dir / "markdown" / f"{slug}.md"

        if markdown_path.exists() and not force:
            markdown = markdown_path.read_text(encoding="utf-8")
            # Only use cached result if it has enough content; otherwise re-upload
            if len(markdown.strip()) >= MIN_MARKDOWN_CHARS:
                full_md = extracted_dir / "full.md"
                return MinerUArtifacts(
                    slug=slug,
                    raw_zip=raw_zip,
                    extracted_dir=extracted_dir,
                    full_md=full_md,
                    markdown_copy=markdown_path,
                    markdown=markdown,
                )

        session = requests.Session()
        try:
            zip_url = self._upload_and_poll(session, pdf_path, data_id)
        finally:
            session.close()

        # Save zip
        raw_zip.parent.mkdir(parents=True, exist_ok=True)
        if raw_zip.exists() and force:
            raw_zip.unlink()
        self._download_binary(zip_url, raw_zip)

        # Extract all sidecar files
        if extracted_dir.exists() and force:
            shutil.rmtree(extracted_dir)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(raw_zip) as archive:
            archive.extractall(extracted_dir)

        # Find full.md
        full_md = extracted_dir / "full.md"
        if not full_md.is_file():
            candidates = sorted(extracted_dir.rglob("*.md"))
            if not candidates:
                raise MinerUError(f"No Markdown found in MinerU result for {pdf_path.name}.")
            full_md = candidates[0]

        # Rewrite image paths and save markdown copy
        raw_markdown = full_md.read_text(encoding="utf-8")
        rewritten = _rewrite_image_paths(raw_markdown, slug)
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(rewritten, encoding="utf-8")

        return MinerUArtifacts(
            slug=slug,
            raw_zip=raw_zip,
            extracted_dir=extracted_dir,
            full_md=full_md,
            markdown_copy=markdown_path,
            markdown=rewritten,
        )

    def _upload_and_poll(self, session: requests.Session, pdf_path: Path, data_id: str) -> str:
        result = self._post(session, "/api/v4/file-urls/batch", {
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
            "model_version": self.model_version,
            "files": [{"name": pdf_path.name, "is_ocr": self.ocr, "data_id": data_id}],
        })
        data = result.get("data") or {}
        upload_urls = data.get("file_urls") or []
        if not upload_urls:
            raise MinerUError("MinerU did not return an upload URL.")
        batch_id = str(data.get("batch_id") or "").strip()
        if not batch_id:
            raise MinerUError("MinerU did not return a batch_id.")

        with pdf_path.open("rb") as handle:
            resp = requests.put(upload_urls[0], data=handle, timeout=300)
        resp.raise_for_status()

        return self._poll(session, batch_id, data_id)

    def _poll(self, session: requests.Session, batch_id: str, data_id: str) -> str:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            payload = self._get(session, f"/api/v4/extract-results/batch/{batch_id}")
            items = ((payload.get("data") or {}).get("extract_result")) or []
            for item in items:
                if item.get("data_id") != data_id:
                    continue
                state = str(item.get("state") or "").strip().lower()
                if state in SUCCESS_STATES:
                    zip_url = str(item.get("full_zip_url") or "").strip()
                    if not zip_url:
                        raise MinerUError("MinerU returned done without full_zip_url.")
                    return zip_url
                if state in FAILURE_STATES:
                    raise MinerUError(f"MinerU parsing failed: {item.get('err_msg') or state}")
            time.sleep(max(1, self.poll_interval))
        raise MinerUError(f"MinerU timed out after {self.timeout_seconds // 60} minutes.")

    def _extract_markdown_from_zip(self, zip_url: str, tmpdir: Path) -> str:
        zip_path = tmpdir / "result.zip"
        self._download_binary(zip_url, zip_path)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(tmpdir)
        full_md = tmpdir / "full.md"
        if not full_md.is_file():
            candidates = sorted(tmpdir.rglob("*.md"))
            if not candidates:
                raise MinerUError("No Markdown file found in MinerU result zip.")
            full_md = candidates[0]
        return full_md.read_text(encoding="utf-8")

    @staticmethod
    def _download_binary(url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=300) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)


def configured_mineru_client() -> MinerUClient | None:
    from app.config import settings
    if not settings.mineru_api_token:
        return None
    return MinerUClient(
        token=settings.mineru_api_token,
        base_url=settings.mineru_base_url,
        language=settings.mineru_language,
        model_version=settings.mineru_model_version,
        enable_formula=settings.mineru_enable_formula,
        enable_table=settings.mineru_enable_table,
        ocr=settings.mineru_ocr,
        poll_interval_seconds=settings.mineru_poll_interval_seconds,
        timeout_minutes=settings.mineru_timeout_minutes,
    )
