#!/usr/bin/env python3
"""Batch upload + extract a folder of PDFs through a running LabKAG backend.

Resumable: writes a manifest after every paper and skips already-succeeded
papers on re-run (unless --force). Reuses pre-parsed MinerU output via
--mineru-output-dir (matches mineru_batch_parse.py's output layout).

Ingest is intentionally NOT part of this script -- extraction results are
already persisted server-side (data/extractions/{document_id}.json) and can
be ingested into the graph separately once Neo4j is available.

Usage:
    python scripts/batch_extract_papers.py \
        --input-dir "D:/Git_projects/Self_test/xmart_55" \
        --mineru-output-dir "D:/Git_projects/Self_test/output_mineru" \
        --project-id xmart_55 \
        --manifest "D:/Git_projects/Self_test/output_mineru/extract_manifest.json"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch upload + extract PDFs via LabKAG.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--mineru-output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--extract-level", default="basic", choices=["basic", "detailed"])
    parser.add_argument(
        "--manifest", type=Path, help="Defaults to <mineru-output-dir>/extract_manifest.json"
    )
    parser.add_argument("--limit", type=int, default=0, help="Max PDFs to process. 0 = all.")
    parser.add_argument("--force", action="store_true", help="Reprocess even if already succeeded.")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=10.0)
    parser.add_argument("--sleep-seconds", type=float, default=1.0)
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"papers": {}}


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def upload(base_url: str, pdf_path: Path, timeout: int) -> dict:
    with pdf_path.open("rb") as handle:
        response = requests.post(
            f"{base_url}/v1/papers/upload",
            files={"file": (pdf_path.name, handle, "application/pdf")},
            timeout=timeout,
        )
    response.raise_for_status()
    return response.json()


def extract(
    base_url: str,
    file_id: str,
    project_id: str,
    extract_level: str,
    mineru_output_dir: Path,
    timeout: int,
) -> dict:
    payload = {
        "file_id": file_id,
        "project_id": project_id,
        "extract_level": extract_level,
        "mineru_output_dir": str(mineru_output_dir),
    }
    response = requests.post(
        f"{base_url}/v1/papers/extract", json=payload, timeout=timeout
    )
    response.raise_for_status()
    return response.json()


def process_one(args: argparse.Namespace, pdf_path: Path) -> dict:
    upload_body = upload(args.base_url, pdf_path, args.timeout)
    file_id = upload_body["data"]["file_id"]

    extract_body = extract(
        args.base_url,
        file_id,
        args.project_id,
        args.extract_level,
        args.mineru_output_dir,
        args.timeout,
    )
    if extract_body.get("status") != "success":
        errors = extract_body.get("errors") or []
        message = errors[0]["message"] if errors else "unknown extraction failure"
        raise RuntimeError(message)

    paper_extraction = extract_body["data"]["paper_extraction"]
    return {
        "status": "ok",
        "file_id": file_id,
        "document_id": paper_extraction["document_id"],
        "paper_id": paper_extraction["paper"]["paper_id"],
        "title": paper_extraction["paper"]["title"],
        "warnings": extract_body.get("warnings") or [],
    }


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest or (args.mineru_output_dir / "extract_manifest.json")

    if not args.input_dir.is_dir():
        raise SystemExit(f"Input directory does not exist: {args.input_dir}")

    pdfs = sorted(args.input_dir.rglob("*.pdf"))
    if args.limit > 0:
        pdfs = pdfs[: args.limit]

    manifest = load_manifest(manifest_path)
    papers: dict = manifest.setdefault("papers", {})

    targets = [
        pdf for pdf in pdfs
        if args.force or papers.get(pdf.name, {}).get("status") != "ok"
    ]
    print(f"Found {len(pdfs)} PDF(s), {len(targets)} pending  |  manifest: {manifest_path}\n")

    for index, pdf_path in enumerate(targets, start=1):
        attempts = 0
        last_error = ""
        while attempts < args.max_attempts:
            attempts += 1
            try:
                result = process_one(args, pdf_path)
                papers[pdf_path.name] = result
                print(f"[{index}/{len(targets)}] [ok] {pdf_path.name} -> {result['title'][:70]}")
                break
            except requests.HTTPError as exc:
                last_error = f"HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            except Exception as exc:  # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
            print(
                f"[{index}/{len(targets)}] [retry {attempts}/{args.max_attempts}] "
                f"{pdf_path.name}: {last_error}"
            )
            if attempts < args.max_attempts:
                time.sleep(args.retry_delay)
        else:
            papers[pdf_path.name] = {"status": "failed", "error": last_error}
            print(f"[{index}/{len(targets)}] [failed] {pdf_path.name}: {last_error}")

        write_manifest(manifest_path, manifest)
        if args.sleep_seconds:
            time.sleep(args.sleep_seconds)

    ok = sum(1 for p in papers.values() if p.get("status") == "ok")
    failed = sum(1 for p in papers.values() if p.get("status") == "failed")
    print(f"\n=== Summary ===\nOK: {ok}  Failed: {failed}  Total tracked: {len(papers)}")
    print(f"Manifest: {manifest_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
