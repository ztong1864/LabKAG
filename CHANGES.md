# What's been added

Summary of the features built on top of LabKAG's original v0.1 scope
(extraction, evidence binding, OpenSPG/Neo4j ingest). Grouped by area.

## PDF parsing: MinerU integration

- `app/adapters/mineru_client.py` — replaces PyMuPDF-only parsing with
  MinerU (layout-aware Markdown, tables, formulas), falling back to
  PyMuPDF only when MinerU is unavailable or returns too little content
  (`app/services/pdf_parser.py`, `app/storage/parsed_backup_dir`).
- **True batch API support** — `MinerUClient.materialize_batch()` uploads
  multiple PDFs in a single MinerU batch request instead of one request per
  file.
- `scripts/mineru_batch_parse.py` — standalone CLI for bulk-parsing a
  folder of PDFs. No server required. **Skips already-parsed files by
  default** (checks for existing cached Markdown before calling MinerU
  again); pass `--force` to reprocess. Configurable output directory via
  `--output-dir`, so different batches/projects can keep their MinerU
  output separate.
- `mineru_output_dir` is also a **per-request field on
  `POST /v1/papers/extract`** — the live extraction endpoint can reuse a
  pre-parsed batch instead of calling MinerU again, as long as the original
  filename is known (see next point).
- **Cache-key fix**: `/v1/papers/upload` renames every file to
  `data/uploads/{file_id}.pdf`, which used to break MinerU's cache lookup
  (it was keyed on the internal file_id, not the paper's real name). Fixed
  by persisting the original filename alongside the upload
  (`FileStore.original_name()`) and threading it through as
  `slug_source` — so a batch already parsed by `mineru_batch_parse.py` gets
  reused by `/v1/papers/extract` instead of silently re-parsed.
- `scripts/batch_extract_papers.py` — resumable batch upload+extract driver
  against a running server. Writes a manifest after every paper, skips
  already-succeeded papers on re-run, bounded retries with backoff.

## Taxonomy-based topic matching

A per-project controlled vocabulary and a precision-first matching engine,
designed specifically to avoid a known failure mode in naive keyword-based
literature discovery: a single weak keyword match silently pulling
unrelated papers into a result set.

- **Taxonomy CRUD** — `GET/POST /v1/projects/{id}/taxonomy`
  (`app/services/taxonomy_service.py`, `app/storage/taxonomy_store.py`).
  Editing a taxonomy in a way that would orphan values already in use
  returns `needs_review` + `affected_papers_count` instead of applying
  silently; requires `confirm=true`.
- **Entity tagging at extraction time** — when a project has a taxonomy,
  `/v1/papers/extract` tags each extracted entity against it via a
  strict-vocabulary LLM call (`app/services/taxonomy_tagger.py`). Entirely
  optional: extraction behaves exactly as before when no taxonomy exists.
- **Topic matching** — `POST /v1/papers/match-topic`
  (`app/services/topic_matcher.py`). Given an already-decomposed topic plan
  (essential vs. supporting concepts), scores every paper in a project
  using a **corroboration rule**: a paper is only `confirmed` if it clears
  ≥2 independent signals (distinct essential-concept matches, or one
  essential match backed by a Result/Conclusion node plus evidence
  co-occurrence) — never a single weak hit. Results are split into
  `confirmed`/`borderline` tiers, never silently padded to hit a target
  count.
- **Where the "intelligence" lives**: topic decomposition and taxonomy
  proposal (both need LLM reasoning) live in the sibling
  `labkag-reviewer-skill` folder (agent/Claude-side), not in this backend.
  The backend only validates an already-built plan deterministically and
  executes the graph/embedding scoring — it never calls an LLM at query
  time. This split follows a separate design document
  (`LabKAG概要设计文档-v1.1`) that states the same invariant for a
  parallel/future architecture.
- `scripts/backfill_taxonomy_tags.py` — resumable retagging for papers
  ingested before a taxonomy existed.

Design doc: none written separately for this feature (developed directly
through iterative brainstorming in-session); see commit history from
`feat(taxonomy): M1 ...` through `M8 ...`.

## Graph backend: SQLite (WAL) + sqlite-vec, as an alternative to Neo4j

Neo4j requires a separately running server process. Since that's not
always available (e.g. no Docker), LabKAG now supports a second backend
that needs **zero external infrastructure** — a single file.

- **`GRAPH_BACKEND=sqlite`** — opt-in; `neo4j` remains the default, no
  behavior change for existing Neo4j configurations. Set this (or
  `SQLITE_DB_PATH` to override the file location, default `data/graph.db`)
  to skip needing Neo4j entirely.
- `app/adapters/sqlite_graph_store.py` / `sqlite_query_store.py` — same
  interface as the Neo4j adapters (`write_graph`, `search_evidence`), so
  nothing above the factory layer (`GraphClient`, `KAGClient`,
  `skill_orchestrator`) needed to change.
- Vector search via `sqlite-vec` (optional — falls back to keyword search
  automatically if the extension isn't available, same degrade-gracefully
  posture as the existing embedding/MinerU fallbacks).
- **Current scope**: `write_graph` + `search_evidence` only. Taxonomy tag
  filtering and the topic-matcher's project-scoped reads
  (`list_papers`, `fetch_entities_for_topic_matching`,
  `count_papers_with_tag_values`) are still Neo4j-only — deliberately
  deferred rather than decided in a rush.
- Found and fixed a real bug while verifying this end-to-end:
  `kag_client.py` had its own hardcoded Neo4j-only construction from an
  earlier milestone, bypassing the query-store factory entirely —
  `/v1/evidence/search` returned an error against the SQLite backend even
  though the factory already supported it. Now routes through the shared
  factory like everything else.

Design doc: `docs/superpowers/specs/2026-07-21-sqlite-graph-backend-design.md`

## Ops / diagnostics

- `scripts/test_neo4j_connection.py` — standalone pre-flight check
  (distinguishes "wrong password" from "nothing listening on that port").

## Test coverage

148 tests passing at the time of writing, `ruff` clean throughout. Most
new adapters (SQLite backend in particular) are tested against a real
temp-file database rather than mocks — genuinely simpler than the Neo4j
adapter's hand-rolled fake-driver test doubles.
