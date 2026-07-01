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

Extraction uses the configured LLM path. If the LLM provider is unavailable,
the endpoint returns `status=failed` with `extraction_failed`.

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
uses the configured graph backend. Graph write failures return
`graph_write_failed`.

The default v0.1 real backend is Neo4j:

```env
MOCK_KAG=false
GRAPH_BACKEND=neo4j
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=labkagneo4j
NEO4J_DATABASE=neo4j
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

The applied relation names are:

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

This endpoint searches matching `Evidence` nodes from Neo4j and builds:

```text
answer
related_entities
reasoning_path
confidence
evidence
```

## Search Evidence

`POST /v1/evidence/search`

```json
{
  "query": "catalytic activity",
  "project_id": "labkag_demo",
  "paper_id": "paper_001",
  "entity_types": ["Result"],
  "top_k": 10
}
```

`query` matches against `Evidence.source_text`. `paper_id` is optional and
narrows the search to one paper.
