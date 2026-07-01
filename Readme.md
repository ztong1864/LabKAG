# LabKAG

LabKAG v0.1 is a Skill-first FastAPI service for literature knowledge extraction,
evidence binding, Neo4j graph storage, and KAG-style literature querying.

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

Run Neo4j for the local graph backend:

```powershell
docker compose -f deploy\neo4j\docker-compose.yml up -d
```

Run the local closed-loop verification after Neo4j is up:

```powershell
py -3.10 scripts\verify_m8_neo4j_closed_loop.py
```

## v0.1 Scope

Implemented in this first framework pass:

- Unified SkillResponse contract
- PDF upload
- Text PDF parsing through PyMuPDF
- Evidence-ready chunking
- OpenAI-compatible LLM extraction path for M3
- Evidence binding validation
- Configurable graph/KAG adapter for M5
- Real local graph writes through Neo4j
- Evidence search and literature query over Neo4j for M6

Not implemented yet:

- OCR
- Authentication
- Frontend UI
- Embedding/vector retrieval

## LLM Extraction

M3 uses an OpenAI-compatible Chat Completions endpoint. Configure it with:

```powershell
$env:LLM_API_KEY="..."
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4o-mini"
```

`LLM_API_KEY` is required for `/v1/papers/extract`. Missing LLM configuration
returns `extraction_failed`.

## Neo4j Graph Backend

M5 maps `PaperExtractionResult` into graph entities and relations, including
`supportedBy` evidence relations. Ingest and query use the configured Neo4j
backend.

For the current local closed loop, use Neo4j directly:

```powershell
$env:GRAPH_BACKEND="neo4j"
$env:NEO4J_URI="bolt://127.0.0.1:7687"
$env:NEO4J_USER="neo4j"
$env:NEO4J_PASSWORD="labkagneo4j"
$env:NEO4J_DATABASE="neo4j"
```

`POST /v1/papers/ingest` only writes to Neo4j when `confirm=true`.

The root project does not use Docker Compose for the LabKAG API service yet.

Neo4j-only service endpoints:

- Neo4j Browser: `http://127.0.0.1:7474`
- Neo4j Bolt: `bolt://127.0.0.1:7687`

Default local Neo4j credentials:

- Neo4j: `neo4j` / `labkagneo4j`

## M8 Handoff Check

The M8 verification script performs the reproducible Neo4j-only closed loop:

```text
health check
POST /v1/papers/ingest with confirm=true
POST /v1/evidence/search scoped by project_id and paper_id
POST /v1/literature/query scoped by project_id and paper_id
```

It uses fixed `m8_neo4j_only_*` IDs and is safe to run repeatedly because graph
writes use idempotent Neo4j `MERGE` operations.
