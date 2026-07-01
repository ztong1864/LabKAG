# LabKAG API v0.1

All Skill endpoints return:

```json
{
  "status": "success",
  "data": {},
  "evidence": [],
  "warnings": [],
  "errors": [],
  "metadata": {
    "request_id": "req_xxx",
    "project_id": "labkag_demo",
    "created_at": "2026-06-29T00:00:00Z"
  }
}
```

## Routes

```text
GET  /health
POST /v1/papers/upload
POST /v1/papers/extract
POST /v1/papers/ingest
GET  /v1/papers/{paper_id}/knowledge
POST /v1/literature/query
POST /v1/evidence/search
```

## Upload

`POST /v1/papers/upload`

Multipart field:

```text
file=<paper.pdf>
```

## Extract

`POST /v1/papers/extract`

```json
{
  "file_id": "file_xxx",
  "project_id": "labkag_demo",
  "extract_level": "basic",
  "return_chunks": false
}
```

Extraction normally uses the configured LLM path. In development, the service may
return a mock extraction and include a warning such as:

```text
LLM extractor is not configured; used mock extractor.
```

If extraction cannot run, the endpoint returns `status=failed` with an error code
such as `extraction_failed`.

## Ingest

`POST /v1/papers/ingest`

```json
{
  "project_id": "labkag_demo",
  "paper_extraction": {},
  "confirm": true
}
```

When `confirm=false`, ingest performs a dry run. When `confirm=true`, the service
uses the configured OpenSPG adapter. In development mode it may return local mock
statistics; in remote mode write failures return `openspg_write_failed`.

For current OpenSPG container images, many `/v1` endpoints require cookie login.
The adapter can log in before remote writes when these settings are provided:

```env
OPENSPG_ACCOUNT=openspg
OPENSPG_PASSWORD=openspg123
```

The adapter hashes the password as `SHA256(raw_password + "OPENSPG")`, matching
the OpenSPG web login flow. The actual data write endpoint is still being
validated; `/api/graph/write` is not present in the current local image.

## Apply Literature Schema

The v0.1 literature schema is applied through OpenSPG's KGDSL endpoint:

```text
GET  /v1/schemas/getSchemaScript?projectId=1
POST /v1/schemas
```

The adapter method is:

```python
OpenSPGClient(...).apply_literature_schema()
```

OpenSPG requires schema property and relation names to use lowerCamelCase. The
applied relation names are:

```text
proposes
uses
hasCondition
measures
reports
drawsConclusion
hasEvidence
supportedBy
```

For the current local closed loop, use the Neo4j graph-store backend from the
OpenSPG compose deployment:

```env
MOCK_KAG=false
OPENSPG_WRITE_BACKEND=neo4j
OPENSPG_PROJECT_ID=1
OPENSPG_PROJECT_NAME=LabKAG
OPENSPG_NEO4J_URI=neo4j://127.0.0.1:7687
OPENSPG_NEO4J_USER=neo4j
OPENSPG_NEO4J_PASSWORD=openspgneo4j
OPENSPG_NEO4J_DATABASE=neo4j
```

With this backend, `confirm=true` writes the LabKAG extraction graph into Neo4j
using `MERGE`, so repeated writes with the same ids are idempotent at the
node/relationship level. The current graph covers:

```text
Paper
Method
Material
Condition
Metric
Result
Conclusion
Evidence

Paper -> Method / Material / Condition / Metric / Result / Conclusion / Evidence
Extracted objects -> Evidence
```

The official OpenSPG REST data write path is still being validated separately.

When `OPENSPG_PROJECT_NAME` is configured, the adapter checks
`GET /v1/projects/list` before remote writes. If the project does not exist, the
request fails with `openspg_write_failed` and a message such as:

```text
OpenSPG project not found: LabKAG. Create it in OpenSPG before real writes.
```

Current local OpenSPG images require a configured vectorizer/embedding model
before a project can be created from the OpenSPG UI or API. The local `LabKAG`
project has been created with an OpenAI-compatible embedding model and can be
found through `GET /v1/projects/list`.

## Query Literature

`POST /v1/literature/query`

```json
{
  "question": "What does this paper report?",
  "project_id": "labkag_demo",
  "paper_id": "paper_001",
  "top_k": 5
}
```

## Search Evidence

`POST /v1/evidence/search`

```json
{
  "query": "catalytic activity",
  "project_id": "labkag_demo",
  "entity_types": ["Result"],
  "top_k": 10
}
```
