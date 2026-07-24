# LabKAG

LabKAG is a Skill-first FastAPI service for literature knowledge extraction:
PDF parsing, LLM-based structured extraction, evidence-bound graph storage,
KAG-style literature querying, and taxonomy-based topic matching for
building a review-writing paper library.

**Architecture split**: the backend is deterministic at query time — it
never calls an LLM to answer `/v1/literature/query`, `/v1/evidence/search`,
or `/v1/papers/match-topic`. LLM calls only happen at build time (structured
extraction, entity tagging against a taxonomy) and are owned by the caller.
Any step that requires judgment about a domain (what a taxonomy's categories
should be, how to decompose a topic into a match plan) happens in the
agent/skill layer, not in this service — see `labkag-review-skill` (see
below; it lives in a separate repository, not in this one).

## Quickstart

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/init_storage.py
uvicorn app.main:app --reload
```

Run tests:

```powershell
py -3.10 -m pytest -v
py -3.10 -m ruff check .
```

## Features

- **PDF parsing**: MinerU (with batch-API support, caching keyed by original
  filename, and a configurable output directory) with a PyMuPDF fallback
  (`--use-backup`) when MinerU isn't available or a paper needs re-parsing
  without it.
- **LLM extraction**: an OpenAI-compatible Chat Completions client extracts
  `PaperMetadata` + methods/materials/conditions/metrics/results/conclusions,
  each bound to source evidence (`bind_required_evidence`).
- **Dual graph backend**: Neo4j (default) or SQLite in WAL mode +
  `sqlite-vec` (opt-in via `GRAPH_BACKEND=sqlite`) — both implement the same
  adapter interface, so the rest of the service (query, taxonomy tagging,
  topic matching) works identically against either. SQLite never replaces
  Neo4j code; it's a coexisting option, not a migration.
- **Embedding-based search** (opt-in via `ENABLE_EMBEDDING=true`): evidence
  and paper-level embeddings, cosine-similarity re-ranking. Embeddings are
  always a corroborating/ranking signal, never a standalone qualifier for
  topic-match results.
- **Ingest-time deduplication**: `ingest_paper` matches an incoming paper
  against existing papers in the same project by DOI (preferred) or title
  before writing, reusing the existing `paper_id` so MERGE-based upsert
  prevents duplicate Paper nodes from re-extracting the same PDF.
- **Taxonomy-based topic matching**: a per-project controlled vocabulary
  (categories + allowed values + aliases) tags extracted entities at build
  time; `POST /v1/papers/match-topic` scores every paper via a
  **corroboration engine** — a paper is `confirmed` only when it clears a
  two-signal bar (two distinct matched essential categories, or one
  essential match on a Result/Conclusion entity plus shared-evidence
  co-occurrence with another match), `borderline` when it clears a weaker
  bar, and excluded otherwise. A single weak hit (one keyword, one embedding
  nudge) can never alone produce `confirmed`. Results are ranked by
  `match_score` (corroboration strength) and can be scored against an
  optional `target_count` to suggest a principled cutoff — never a hardcoded
  threshold, never padded past what actually qualified.
- **`labkag-review-skill`**: the agent-facing CLI and prompt contracts that
  drive this API — see below.

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Service health check |
| POST | `/v1/papers/upload` | Upload a PDF, get a `file_id` |
| POST | `/v1/papers/extract` | Parse + LLM-extract a paper (optionally tags against a taxonomy) |
| POST | `/v1/papers/ingest` | Write an extraction to the graph (`confirm=true` to actually write) |
| GET | `/v1/papers` | List papers in a project |
| GET | `/v1/papers/{paper_id}/knowledge` | Read back one paper's extracted knowledge |
| POST | `/v1/papers/match-topic` | Score every paper in a project against a `TopicPlan` |
| POST | `/v1/literature/query` | KAG-style literature query over the graph |
| POST | `/v1/evidence/search` | Keyword/vector evidence search |
| GET | `/v1/projects/{project_id}/taxonomy` | Read a project's taxonomy |
| POST | `/v1/projects/{project_id}/taxonomy` | Create/update a taxonomy (`?confirm=true` for breaking edits) |

## Configuration

Key settings (env vars / `.env`, see `app/config.py` for the full list):

```text
GRAPH_BACKEND=neo4j|sqlite          # default neo4j
SQLITE_DB_PATH=data/graph.db        # used when GRAPH_BACKEND=sqlite
NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE

LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

ENABLE_EMBEDDING=true|false
EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL / EMBEDDING_DIM

MINERU_API_TOKEN / MINERU_BASE_URL / MINERU_LANGUAGE / MINERU_MODEL_VERSION

METADATA_DIR=data/metadata          # canonical extraction JSON store
TAXONOMY_DIR=data/taxonomies        # per-project taxonomy JSON store
```

## Neo4j Graph Backend

```powershell
docker compose -f deploy\neo4j\docker-compose.yml up -d
```

```powershell
$env:GRAPH_BACKEND="neo4j"
$env:NEO4J_URI="bolt://127.0.0.1:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="labkagneo4j"
$env:NEO4J_DATABASE="neo4j"
```

`POST /v1/papers/ingest` only writes to Neo4j when `confirm=true`. The root
project does not use Docker Compose for the LabKAG API service itself.

- Neo4j Browser: `http://127.0.0.1:7474`
- Neo4j Bolt: `bolt://127.0.0.1:7687`
- Default local credentials: `neo4j` / `labkagneo4j`

## SQLite Graph Backend

An opt-in alternative to Neo4j for local/single-machine use, no Docker
required — WAL-mode SQLite + `sqlite-vec` for vector search (falls back to
keyword search if the extension isn't available):

```powershell
$env:GRAPH_BACKEND="sqlite"
$env:SQLITE_DB_PATH="data/graph.db"
```

## `labkag-review-skill`

The agent-facing layer that drives this API. **This is the only place it
lives** — `skills/labkag-review-skill/` in the review-writer repository (a
separate repository the user maintains, e.g. `D:\Git_projects\review-writer`
on this machine). There is deliberately no copy of it in this repository:
keeping two copies in sync by hand was a real, recurring source of drift
(stale schema references, a missing bugfix applied to only one copy), so it
was consolidated into the one that's actually wired into the downstream
review-writing pipeline. See its `SKILL.md` there for the full contract. It
separates two independently-callable workflows:

1. **Paper storage building** — ingest a corpus (`batch-extract` +
   `batch-ingest`), bootstrap or rebuild a project's taxonomy (asking the
   user about expected review size and resolving any classification
   ambiguity *before* building — never guessing), tag every paper against
   it, and report the build's actual performance (retag success/failure
   counts, validation warnings) before considering it done.
2. **Paper discovery / recommendation** — given an existing, already-tagged
   project, decompose a topic into a match plan (resolving topic-specific
   ambiguity and expected result size), run `match-topic`, and report
   `confirmed`/`borderline` results with their reasons relayed verbatim,
   never padded to hit a target count.

Storage building must exist before discovery can run against a project
(`taxonomy-get` returning nothing routes back to storage building first);
beyond that, either workflow can be invoked independently against an
already-built project.

An export script (`export_discovery_format.py`, part of `labkag-review-skill`
in the review-writer repo, not this one) can translate a `match-topic`
response into the output format used by a separate
`review-online-paper-discovery` skill, for interop with downstream
review-writing pipelines built against that format.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/init_storage.py` | Create local data directories |
| `scripts/mineru_batch_parse.py` | Standalone bulk MinerU parse over a folder of PDFs |
| `scripts/backfill_taxonomy_tags.py` | Retag already-ingested papers against a project's current taxonomy version |
| `scripts/dedupe_papers.py` | Remove duplicate Paper nodes (same project + title), cascade-deleting their entities/evidence |
| `scripts/init_neo4j_vector_index.py` | Create the Neo4j vector index for evidence embeddings |
| `scripts/test_neo4j_connection.py` | Standalone Neo4j connectivity pre-flight check |
| `scripts/verify_m8_neo4j_closed_loop.py` | Reproducible ingest → search → query closed-loop check against Neo4j |

## Testing

```powershell
py -3.10 -m pytest -v
py -3.10 -m ruff check .
```

177 tests as of the current taxonomy/topic-matching/SQLite-backend work,
covering: extraction/evidence-binding, both graph adapters, the taxonomy
schema/store/service, entity tagging, the topic-matcher corroboration engine
(a dedicated boundary-condition suite asserting a single weak signal can
never alone produce `confirmed`), ingest-time dedup, and the API layer.
