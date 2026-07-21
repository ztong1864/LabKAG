from __future__ import annotations

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
DEFAULT_BATCH_SIZE = 20
NETWORK_RETRY_ATTEMPTS = 3
NETWORK_RETRY_BACKOFF_SECONDS = 5.0


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


@dataclass
class MinerUBatchResult:
    """Outcome of one PDF within a materialize_batch() call."""
    pdf_path: Path
    slug: str
    state: str  # "cached" | "done" | "failed"
    artifacts: MinerUArtifacts | None = None
    error: str | None = None


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


def _output_paths(output_dir: Path, slug: str) -> tuple[Path, Path, Path]:
    raw_zip = output_dir / "raw_zips" / f"{slug}.zip"
    extracted_dir = output_dir / "extracted" / slug
    markdown_path = output_dir / "markdown" / f"{slug}.md"
    return raw_zip, extracted_dir, markdown_path


def _with_retries(call, *, attempts: int = NETWORK_RETRY_ATTEMPTS):
    """Retry a network call a few times on transient connection failures
    (dropped connections, timeouts) so one flaky request doesn't kill an
    hours-long batch run. HTTP error responses (4xx/5xx already raised via
    raise_for_status) are not retried -- only connection-level failures."""
    last_exc: requests.exceptions.RequestException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
            last_exc = exc
            if attempt < attempts:
                time.sleep(NETWORK_RETRY_BACKOFF_SECONDS)
    raise last_exc


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
        response = _with_retries(lambda: session.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            json=payload,
            timeout=60,
        ))
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise MinerUError(f"MinerU API error at {path}: {data.get('msg') or data}")
        return data

    def _get(self, session: requests.Session, path: str) -> dict:
        response = _with_retries(lambda: session.get(
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=60,
        ))
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise MinerUError(f"MinerU API error at {path}: {data.get('msg') or data}")
        return data

    # ---- single-file API (used by the live LabKAG parsing pipeline) ----

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
        cached = None if force else self._read_cache(output_dir, slug)
        if cached is not None:
            return cached

        session = requests.Session()
        try:
            zip_url = self._upload_and_poll(session, pdf_path, f"labkag-{slug}"[:96])
        finally:
            session.close()

        return self._materialize_from_zip_url(pdf_path, output_dir, slug, zip_url, force)

    # ---- batch API (bulk folder parsing, e.g. mineru_batch_parse.py) ----

    def materialize_batch(
        self,
        pdf_paths: list[Path],
        output_dir: Path,
        batch_size: int = DEFAULT_BATCH_SIZE,
        force: bool = False,
        on_progress=None,
    ) -> list[MinerUBatchResult]:
        """Materialize many PDFs, uploading up to batch_size files per MinerU batch request.

        Already-cached PDFs (existing markdown of sufficient length) are skipped
        without any network call unless force=True. on_progress, if given, is
        called with (message: str) for lightweight progress reporting.
        """
        results: dict[Path, MinerUBatchResult] = {}
        pending: list[Path] = []

        for pdf_path in pdf_paths:
            slug = _slugify(pdf_path.stem)
            cached = None if force else self._read_cache(output_dir, slug)
            if cached is not None:
                results[pdf_path] = MinerUBatchResult(
                    pdf_path=pdf_path, slug=slug, state="cached", artifacts=cached
                )
                if on_progress:
                    on_progress(f"[cached] {pdf_path.name}")
            else:
                pending.append(pdf_path)

        session = requests.Session()
        try:
            for start in range(0, len(pending), max(1, batch_size)):
                chunk = pending[start : start + batch_size]
                self._run_one_batch(session, chunk, output_dir, force, results, on_progress)
        finally:
            session.close()

        return [results[p] for p in pdf_paths]

    def _run_one_batch(
        self,
        session: requests.Session,
        pdf_paths: list[Path],
        output_dir: Path,
        force: bool,
        results: dict[Path, MinerUBatchResult],
        on_progress,
    ) -> None:
        slugs = {p: _slugify(p.stem) for p in pdf_paths}
        data_ids = {p: f"{i:03d}-{slugs[p]}"[:96] for i, p in enumerate(pdf_paths, start=1)}

        payload = {
            "enable_formula": self.enable_formula,
            "enable_table": self.enable_table,
            "language": self.language,
            "model_version": self.model_version,
            "files": [
                {"name": p.name, "is_ocr": self.ocr, "data_id": data_ids[p]}
                for p in pdf_paths
            ],
        }
        result = self._post(session, "/api/v4/file-urls/batch", payload)
        data = result.get("data") or {}
        upload_urls = data.get("file_urls") or []
        batch_id = str(data.get("batch_id") or "").strip()
        if not batch_id or len(upload_urls) != len(pdf_paths):
            raise MinerUError(
                f"MinerU batch request failed: got {len(upload_urls)} URLs for "
                f"{len(pdf_paths)} files, batch_id={batch_id!r}."
            )

        for pdf_path, upload_url in zip(pdf_paths, upload_urls, strict=True):

            def _upload_once(pdf_path=pdf_path, upload_url=upload_url):
                with pdf_path.open("rb") as handle:
                    resp = requests.put(upload_url, data=handle, timeout=300)
                resp.raise_for_status()

            _with_retries(_upload_once)
            if on_progress:
                on_progress(f"[upload] {pdf_path.name}")

        if on_progress:
            on_progress(f"[batch] {batch_id} ({len(pdf_paths)} files)")

        id_to_path = {data_ids[p]: p for p in pdf_paths}
        final_states = self._poll_batch(session, batch_id, set(id_to_path), on_progress)

        for data_id, pdf_path in id_to_path.items():
            slug = slugs[pdf_path]
            item = final_states.get(data_id)
            state = str((item or {}).get("state") or "unknown").lower()
            if state not in SUCCESS_STATES:
                err = (item or {}).get("err_msg") or state
                results[pdf_path] = MinerUBatchResult(
                    pdf_path=pdf_path, slug=slug, state="failed", error=str(err)
                )
                continue
            zip_url = str((item or {}).get("full_zip_url") or "").strip()
            if not zip_url:
                results[pdf_path] = MinerUBatchResult(
                    pdf_path=pdf_path,
                    slug=slug,
                    state="failed",
                    error="MinerU returned done without full_zip_url.",
                )
                continue
            try:
                artifacts = self._materialize_from_zip_url(
                    pdf_path, output_dir, slug, zip_url, force
                )
                results[pdf_path] = MinerUBatchResult(
                    pdf_path=pdf_path, slug=slug, state="done", artifacts=artifacts
                )
            except MinerUError as exc:
                results[pdf_path] = MinerUBatchResult(
                    pdf_path=pdf_path, slug=slug, state="failed", error=str(exc)
                )

    def _poll_batch(
        self,
        session: requests.Session,
        batch_id: str,
        tracked_ids: set[str],
        on_progress,
    ) -> dict[str, dict]:
        deadline = time.time() + self.timeout_seconds
        last_states: dict[str, str] = {}
        final_results: dict[str, dict] = {}

        while time.time() < deadline:
            payload = self._get(session, f"/api/v4/extract-results/batch/{batch_id}")
            items = ((payload.get("data") or {}).get("extract_result")) or []
            for item in items:
                data_id = item.get("data_id")
                if data_id not in tracked_ids:
                    continue
                state = str(item.get("state") or "").strip()
                final_results[data_id] = item
                if last_states.get(data_id) != state:
                    last_states[data_id] = state
                    if on_progress:
                        on_progress(f"[poll] {data_id}: {state}")
            if len(final_results) == len(tracked_ids):
                active = [
                    item for item in final_results.values()
                    if str(item.get("state") or "").lower() not in TERMINAL_STATES
                ]
                if not active:
                    return final_results
            time.sleep(max(1, self.poll_interval))
        minutes = self.timeout_seconds // 60
        raise MinerUError(f"MinerU batch {batch_id} timed out after {minutes} minutes.")

    # ---- shared helpers ----

    def _read_cache(self, output_dir: Path, slug: str) -> MinerUArtifacts | None:
        raw_zip, extracted_dir, markdown_path = _output_paths(output_dir, slug)
        if not markdown_path.exists():
            return None
        markdown = markdown_path.read_text(encoding="utf-8")
        if len(markdown.strip()) < MIN_MARKDOWN_CHARS:
            return None
        return MinerUArtifacts(
            slug=slug,
            raw_zip=raw_zip,
            extracted_dir=extracted_dir,
            full_md=extracted_dir / "full.md",
            markdown_copy=markdown_path,
            markdown=markdown,
        )

    def _materialize_from_zip_url(
        self,
        pdf_path: Path,
        output_dir: Path,
        slug: str,
        zip_url: str,
        force: bool,
    ) -> MinerUArtifacts:
        raw_zip, extracted_dir, markdown_path = _output_paths(output_dir, slug)

        raw_zip.parent.mkdir(parents=True, exist_ok=True)
        if raw_zip.exists() and force:
            raw_zip.unlink()
        self._download_binary(zip_url, raw_zip)

        if extracted_dir.exists() and force:
            shutil.rmtree(extracted_dir)
        extracted_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(raw_zip) as archive:
            archive.extractall(extracted_dir)

        full_md = extracted_dir / "full.md"
        if not full_md.is_file():
            candidates = sorted(extracted_dir.rglob("*.md"))
            if not candidates:
                raise MinerUError(f"No Markdown found in MinerU result for {pdf_path.name}.")
            full_md = candidates[0]

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

        def _upload_once():
            with pdf_path.open("rb") as handle:
                resp = requests.put(upload_urls[0], data=handle, timeout=300)
            resp.raise_for_status()

        _with_retries(_upload_once)

        final = self._poll_batch(session, batch_id, {data_id}, None)
        item = final.get(data_id) or {}
        state = str(item.get("state") or "").strip().lower()
        if state not in SUCCESS_STATES:
            raise MinerUError(f"MinerU parsing failed: {item.get('err_msg') or state}")
        zip_url = str(item.get("full_zip_url") or "").strip()
        if not zip_url:
            raise MinerUError("MinerU returned done without full_zip_url.")
        return zip_url

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

        def _download_once():
            with requests.get(url, stream=True, timeout=300) as response:
                response.raise_for_status()
                with dest.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)

        _with_retries(_download_once)


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
