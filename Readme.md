# LabKAG

LabKAG v0.1 is a Skill-first FastAPI service for literature knowledge extraction,
evidence binding, and configurable OpenSPG/KAG integration.

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

## v0.1 Scope

Implemented in this first framework pass:

- Unified SkillResponse contract
- PDF upload
- Text PDF parsing through PyMuPDF
- Evidence-ready chunking
- Mock paper extraction
- OpenAI-compatible LLM extraction path for M3
- Evidence binding validation
- Configurable OpenSPG HTTP ingest path for M5
- Mock KAG literature query and evidence search

Not implemented yet:

- Real KAG reasoning
- OCR
- Authentication
- Frontend UI

## LLM Extraction

M3 uses an OpenAI-compatible Chat Completions endpoint. Configure it with:

```powershell
$env:LLM_API_KEY="..."
$env:LLM_BASE_URL="https://api.openai.com/v1"
$env:LLM_MODEL="gpt-4o-mini"
$env:ALLOW_MOCK_EXTRACTOR="true"
```

`ALLOW_MOCK_EXTRACTOR=true` allows development fallback when `LLM_API_KEY` is
missing, and also allows `extract_level=mock` for explicit mock extraction.
Set it to `false` in stricter environments so missing LLM configuration returns
`extraction_failed` instead of silently using mock data.

## OpenSPG Ingest

M5 maps `PaperExtractionResult` into graph entities and relations, including
`supported_by` evidence relations. By default `MOCK_KAG=true`, so ingest returns
local write statistics without calling OpenSPG.

To call an OpenSPG-compatible HTTP write endpoint:

```powershell
$env:MOCK_KAG="false"
$env:OPENSPG_BASE_URL="https://openspg.example.com"
$env:OPENSPG_WRITE_PATH="/api/graph/write"
$env:OPENSPG_API_KEY="..."
$env:OPENSPG_PROJECT_ID="labkag"
```

`POST /v1/papers/ingest` only writes remotely when `confirm=true`.

## Local OpenSPG Backend

The OpenSPG backend compose stack lives under `deploy/openspg/`:

```powershell
Copy-Item deploy\openspg\.env.example deploy\openspg\.env
docker compose --env-file deploy\openspg\.env -f deploy\openspg\docker-compose.yml up -d
```

The root project does not use Docker Compose for the LabKAG API service yet.
