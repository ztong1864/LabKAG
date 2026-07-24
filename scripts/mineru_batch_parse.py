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


def _load_manifest(manifest_path: Path) -> dict:
    """Load manifest.json if present so runs accumulate instead of overwrite.

    manifest.json has no functional role in the actual parse-skip caching
    (MinerUClient._read_cache checks the filesystem directly), but it's the
    human-facing record of every PDF ever processed by this script, possibly
    across many invocations with different --input-dir values. A missing or
    unreadable file (including the old pre-merge schema, which had no
    "papers" key) is treated as an empty starting point.
    """
    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}
    data.setdefault("tool", "labkag-mineru-batch-parse")
    if not isinstance(data.get("papers"), dict):
        data["papers"] = {}
    return data


def _write_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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

    manifest_path = output_dir / "manifest.json"
    manifest = _load_manifest(manifest_path)
    manifest["output_dir"] = str(output_dir)
    manifest["last_run"] = {
        "input_dir": str(input_dir),
        "started_at": _now_utc(),
        "settings": {
            "language": args.language,
            "model_version": args.model_version,
            "enable_formula": not args.disable_formula,
            "enable_table": not args.disable_table,
            "ocr": args.ocr,
            "batch_size": args.batch_size,
        },
        "queued": len(pdfs),
    }
    papers: dict = manifest["papers"]

    results = client.materialize_batch(
        pdfs,
        output_dir,
        batch_size=args.batch_size,
        force=args.force,
        on_progress=print,
    )

    run_completed = run_failed = run_skipped = 0
    for result in results:
        pdf_name = result.pdf_path.name
        if result.state == "cached":
            print(f"[skip] {pdf_name} -> existing {result.slug}.md")
            papers[pdf_name] = {
                "slug": result.slug,
                "state": "skipped",
                "updated_at": _now_utc(),
            }
            run_skipped += 1
        elif result.state == "done" and result.artifacts:
            a = result.artifacts
            papers[pdf_name] = {
                "slug": a.slug,
                "state": "done",
                "raw_zip": str(a.raw_zip),
                "extracted_dir": str(a.extracted_dir),
                "full_md": str(a.full_md),
                "markdown_copy": str(a.markdown_copy),
                "markdown_chars": len(a.markdown),
                "updated_at": _now_utc(),
            }
            print(
                f"[done] {pdf_name} -> {a.markdown_copy.name} "
                f"({len(a.markdown):,} chars)"
            )
            run_completed += 1
        else:
            papers[pdf_name] = {
                "slug": result.slug,
                "state": "failed",
                "error": result.error or "unknown error",
                "updated_at": _now_utc(),
            }
            print(f"[failed] {pdf_name}: {result.error}")
            run_failed += 1
        _write_manifest(manifest_path, manifest)

    manifest["last_run"]["finished_at"] = _now_utc()
    manifest["last_run"]["completed_count"] = run_completed
    manifest["last_run"]["failed_count"] = run_failed
    manifest["last_run"]["skipped_count"] = run_skipped
    manifest["updated_at"] = _now_utc()
    total_done = sum(1 for p in papers.values() if p.get("state") == "done")
    total_failed = sum(1 for p in papers.values() if p.get("state") == "failed")
    total_skipped = sum(1 for p in papers.values() if p.get("state") == "skipped")
    manifest["total_done"] = total_done
    manifest["total_failed"] = total_failed
    manifest["total_skipped"] = total_skipped
    _write_manifest(manifest_path, manifest)

    print("\n=== This run ===")
    print(f"Done: {run_completed}  Failed: {run_failed}  Skipped: {run_skipped}")
    print("\n=== Cumulative (all papers recorded in this manifest) ===")
    print(
        f"Done: {total_done}  Failed: {total_failed}  Skipped: {total_skipped}  "
        f"Total: {len(papers)}"
    )
    print(f"Manifest: {manifest_path}")

    return 0 if run_failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
