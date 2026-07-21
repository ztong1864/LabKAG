#!/usr/bin/env python3
"""Batch-parse a local PDF library into Markdown with the MinerU API.

Standalone CLI, no running LabKAG server required. Replaces the separate
review-writer mineru-precise-parse skill: same output layout
(raw_zips/, extracted/<slug>/, markdown/, manifest.json), same batching and
skip-existing behavior, built on top of app.adapters.mineru_client.MinerUClient.

Usage:
    python scripts/mineru_batch_parse.py --input-dir path/to/pdfs
    python scripts/mineru_batch_parse.py --pdf path/to/one.pdf --output-dir out/
    python scripts/mineru_batch_parse.py --input-dir path/to/pdfs --limit 2
    python scripts/mineru_batch_parse.py --input-dir path/to/pdfs --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# PDF filenames routinely contain non-ASCII characters (accents, unicode
# dashes). The default console encoding on some Windows locales (e.g. GBK)
# can't represent them, which crashes plain print() mid-batch. Force UTF-8
# with a safe fallback so a stray filename never kills a long-running batch.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.adapters.mineru_client import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    MinerUClient,
    _now_utc,
)

DEFAULT_OUTPUT_DIR = Path("data/parsed")


def resolve_token(args: argparse.Namespace) -> str:
    token = (args.token or "").strip()
    if token:
        return token
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    if token:
        return token
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from app.config import settings
        if settings.mineru_api_token:
            return settings.mineru_api_token
    except Exception:
        pass
    raise SystemExit(
        "Missing MinerU API token. Pass --token, set MINERU_API_TOKEN, or set "
        "MINERU_API_TOKEN in LabKAG's .env file."
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-parse local PDFs into Markdown via the MinerU API."
    )
    parser.add_argument("--input-dir", type=Path, help="Directory to scan recursively for *.pdf.")
    parser.add_argument("--pdf", type=Path, help="Parse a single PDF instead of a directory.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
                         help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--token", help="MinerU API token. Falls back to MINERU_API_TOKEN / .env.")
    parser.add_argument("--language", default="en")
    parser.add_argument("--model-version", default="vlm")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--limit", type=int, default=0, help="Max PDFs to process. 0 = all.")
    parser.add_argument("--poll-interval", type=int, default=5)
    parser.add_argument("--timeout-minutes", type=int, default=30)
    parser.add_argument("--disable-formula", action="store_true")
    parser.add_argument("--disable-table", action="store_true")
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--force", action="store_true",
                         help="Reprocess files even if already parsed.")
    args = parser.parse_args()
    if not args.input_dir and not args.pdf:
        parser.error("one of --input-dir or --pdf is required")
    return args


def discover_pdfs(input_dir: Path, output_dir: Path, limit: int) -> list[Path]:
    output_resolved = output_dir.resolve()
    pdfs = [
        path
        for path in sorted(input_dir.rglob("*.pdf"))
        if path.is_file() and output_resolved not in path.resolve().parents
    ]
    if limit > 0:
        pdfs = pdfs[:limit]
    return pdfs


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    token = resolve_token(args)

    if args.pdf:
        pdf_path = args.pdf.resolve()
        if not pdf_path.is_file():
            raise SystemExit(f"PDF does not exist: {pdf_path}")
        pdfs = [pdf_path]
        input_dir = pdf_path.parent
    else:
        input_dir = args.input_dir.resolve()
        if not input_dir.is_dir():
            raise SystemExit(f"Input directory does not exist: {input_dir}")
        pdfs = discover_pdfs(input_dir, output_dir, args.limit)

    if not pdfs:
        print("No PDFs found.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)

    client = MinerUClient(
        token=token,
        language=args.language,
        model_version=args.model_version,
        enable_formula=not args.disable_formula,
        enable_table=not args.disable_table,
        ocr=args.ocr,
        poll_interval_seconds=args.poll_interval,
        timeout_minutes=args.timeout_minutes,
    )

    print(f"Found {len(pdfs)} PDF(s)  |  output: {output_dir}\n")

    manifest: dict = {
        "tool": "labkag-mineru-batch-parse",
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "created_at": _now_utc(),
        "settings": {
            "language": args.language,
            "model_version": args.model_version,
            "enable_formula": not args.disable_formula,
            "enable_table": not args.disable_table,
            "ocr": args.ocr,
            "batch_size": args.batch_size,
        },
        "queued": len(pdfs),
        "completed": [],
        "failed": [],
        "skipped": [],
    }

    results = client.materialize_batch(
        pdfs,
        output_dir,
        batch_size=args.batch_size,
        force=args.force,
        on_progress=print,
    )

    for result in results:
        if result.state == "cached":
            print(f"[skip] {result.pdf_path.name} -> existing {result.slug}.md")
            manifest["skipped"].append({"pdf_name": result.pdf_path.name, "slug": result.slug})
            continue
        if result.state == "done" and result.artifacts:
            a = result.artifacts
            record = {
                "pdf_name": result.pdf_path.name,
                "slug": a.slug,
                "state": "done",
                "raw_zip": str(a.raw_zip),
                "extracted_dir": str(a.extracted_dir),
                "full_md": str(a.full_md),
                "markdown_copy": str(a.markdown_copy),
                "markdown_chars": len(a.markdown),
            }
            manifest["completed"].append(record)
            print(
                f"[done] {result.pdf_path.name} -> {a.markdown_copy.name} "
                f"({len(a.markdown):,} chars)"
            )
        else:
            manifest["failed"].append({
                "pdf_name": result.pdf_path.name,
                "slug": result.slug,
                "error": result.error or "unknown error",
            })
            print(f"[failed] {result.pdf_path.name}: {result.error}")

    manifest["finished_at"] = _now_utc()
    manifest["completed_count"] = len(manifest["completed"])
    manifest["failed_count"] = len(manifest["failed"])
    manifest["skipped_count"] = len(manifest["skipped"])

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    print(
        f"Done: {manifest['completed_count']}  "
        f"Failed: {manifest['failed_count']}  "
        f"Skipped: {manifest['skipped_count']}"
    )
    print(f"Manifest: {manifest_path}")

    return 0 if not manifest["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
