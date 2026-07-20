"""Test MinerU full materialize: saves zip, extracted sidecars, images, markdown, and manifest."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("MINERU_API_TOKEN", "sk-rMqWfOOqZvocRnpAW9HlRGtuYl5Dql2uBbHNQWgXqOcX9BAv")

from app.adapters.mineru_client import MinerUError, _now_utc, configured_mineru_client
from app.services.pdf_parser import _document_from_markdown
from app.utils.ids import new_id

INPUT_DIR = Path(r"D:\Git_projects\review-writer-main\test-paper-storage-rag")
OUTPUT_DIR = Path("data/parsed")
FORCE = "--force" in sys.argv

client = configured_mineru_client()
if client is None:
    print("ERROR: MINERU_API_TOKEN not set.")
    sys.exit(1)

pdfs = sorted(INPUT_DIR.glob("*.pdf"))
print(f"Found {len(pdfs)} PDFs  |  output: {OUTPUT_DIR.resolve()}\n")

manifest: dict = {
    "tool": "labkag-mineru-parse",
    "input_dir": str(INPUT_DIR),
    "output_dir": str(OUTPUT_DIR.resolve()),
    "created_at": _now_utc(),
    "settings": {
        "language": client.language,
        "model_version": client.model_version,
        "enable_formula": client.enable_formula,
        "enable_table": client.enable_table,
        "ocr": client.ocr,
    },
    "queued": len(pdfs),
    "completed": [],
    "failed": [],
}

for pdf in pdfs:
    slug_preview = pdf.stem[:50]
    md_check = OUTPUT_DIR / "markdown" / f"{slug_preview}"

    print(f"[parse] {pdf.name} ...", end=" ", flush=True)
    try:
        artifacts = client.materialize(pdf, OUTPUT_DIR, force=FORCE)

        doc = _document_from_markdown(artifacts.markdown, new_id("doc"), pdf.name)

        # Count sidecar files and images
        sidecars = [f for f in artifacts.extracted_dir.iterdir() if f.is_file()]
        images_dir = artifacts.extracted_dir / "images"
        image_count = len(list(images_dir.glob("*"))) if images_dir.exists() else 0

        record = {
            "pdf_name": pdf.name,
            "slug": artifacts.slug,
            "state": "done",
            "title": doc.title,
            "sections": len(doc.pages),
            "markdown_chars": len(artifacts.markdown),
            "image_count": image_count,
            "sidecar_files": [f.name for f in sidecars],
            "raw_zip": str(artifacts.raw_zip),
            "extracted_dir": str(artifacts.extracted_dir),
            "full_md": str(artifacts.full_md),
            "markdown_copy": str(artifacts.markdown_copy),
        }
        manifest["completed"].append(record)
        status = "skip" if not artifacts.raw_zip.stat().st_size == 0 else "ok"
        print(f"ok — {len(doc.pages)} sections, {image_count} images, {len(artifacts.markdown):,} chars")

    except MinerUError as exc:
        print(f"FAILED: {exc}")
        manifest["failed"].append({"pdf_name": pdf.name, "state": "failed", "error": str(exc)})

manifest["finished_at"] = _now_utc()
manifest["completed_count"] = len(manifest["completed"])
manifest["failed_count"] = len(manifest["failed"])

manifest_path = OUTPUT_DIR / "manifest.json"
manifest_path.parent.mkdir(parents=True, exist_ok=True)
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"\n=== Summary ===")
print(f"OK: {manifest['completed_count']}  Failed: {manifest['failed_count']}")
print(f"\nOutput layout:")
print(f"  {OUTPUT_DIR}/raw_zips/        — original MinerU zip files")
print(f"  {OUTPUT_DIR}/extracted/<slug>/ — full.md, images/, layout.json, *_content_list.json, *_model.json")
print(f"  {OUTPUT_DIR}/markdown/         — rewritten .md files with fixed image paths")
print(f"  {OUTPUT_DIR}/manifest.json     — tracking manifest")
print(f"\nManifest written to: {manifest_path.resolve()}")

for r in manifest["completed"]:
    print(f"  ✓ {r['pdf_name']} — {r['sections']} sections, {r['image_count']} images | {r.get('title','')[:55]}")
for r in manifest["failed"]:
    print(f"  ✗ {r['pdf_name']} — {r['error']}")
