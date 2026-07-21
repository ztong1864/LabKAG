# SQLite (WAL) + sqlite-vec graph backend — design

## Context

LabKAG's only graph backend is Neo4j, which requires a separately running
server process. During a real batch-extraction run this session, that
became a concrete blocker: no Docker was available in the environment, so
there was no way to stand up Neo4j at all, and `/v1/papers/ingest` had no
usable path forward.

Separately, an earlier-discovered companion design document
(`LabKAG概要设计文档-v1.1`, describing a parallel/future TypeScript+MCP
architecture for LabKAG under a broader SciWork ecosystem) specifies exactly
this storage shape for its own target design: a single SQLite (WAL) file
plus `sqlite-vec` for vector search, with `nodes`/`edges` tables. Adding
this backend to the current Python service doesn't diverge from where the
project is headed — it moves this codebase closer to it.

The goal: let ingest and evidence search work with zero external
infrastructure, without touching the existing Neo4j path at all.

## Scope

- **Coexistence, not replacement.** Neo4j code is untouched. `GRAPH_BACKEND`
  gains a second valid value, `sqlite`, alongside the existing `neo4j`.
  `neo4j` remains the default — no behavior change for existing
  configurations.
- **Basic subset first.** Only `write_graph` and `search_evidence` (the two
  methods `GraphClient`/`KAGClient` actually call) get a SQLite
  implementation. Taxonomy tag filtering (`count_papers_with_tag_values`)
  and the topic-matcher's project-scoped reads (`list_papers`,
  `fetch_entities_for_topic_matching`) remain Neo4j-only for now — those
  need a schema decision (flattened tag columns vs. JSON extraction) that's
  deliberately deferred to a follow-up design rather than made accidentally
  here.
- **No cross-backend migration.** Switching `GRAPH_BACKEND` starts from an
  empty graph on the new backend. This is a stated limitation, not a bug.

## Architecture

Both new stores implement the exact same interface `Neo4jGraphStore`/
`Neo4jQueryStore` already expose, so nothing above the factory layer
changes:

```
skill_orchestrator.py (unchanged)
       │
       ▼
graph_store_factory.build_graph_store()   query_store_factory.build_query_store()
       │  dispatch on settings.graph_backend
       ├─ "neo4j"  (default, unchanged) → Neo4jGraphStore / Neo4jQueryStore
       └─ "sqlite" (new, opt-in)        → SQLiteGraphStore / SQLiteQueryStore
                                              │
                                              ▼
                                    data/graph.db (WAL mode)
                                    nodes / edges + evidence_vec (if sqlite-vec loads)
```

## Schema

```sql
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,                 -- 'Paper' | 'Method' | ... | 'Evidence'
    project_id TEXT NOT NULL DEFAULT '',
    properties TEXT NOT NULL            -- JSON blob, same shape as a Neo4j node's properties
);
CREATE INDEX IF NOT EXISTS idx_nodes_project_type ON nodes(project_id, type);

CREATE TABLE IF NOT EXISTS edges (
    source_id TEXT NOT NULL, relation_type TEXT NOT NULL, target_id TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (source_id, relation_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);

-- only created if the sqlite-vec extension loads successfully
CREATE VIRTUAL TABLE IF NOT EXISTS evidence_vec
    USING vec0(evidence_id TEXT PRIMARY KEY, embedding FLOAT[1536]);
```

Properties are one JSON blob per node. This is simpler than the Neo4j
adapter here: Neo4j needs `_property_value()`/`_safe_token()` because Cypher
labels/property values must be flat scalars and valid identifiers; SQLite
has neither constraint. `write_graph` just does
`json.dumps(entity["properties"])`. Tags stay nested in that JSON, untouched
— taxonomy filtering is out of scope for this pass.

## New components

| File | Purpose |
|---|---|
| `app/adapters/sqlite_connection.py` | `connect(db_path, embedding_dim) -> sqlite3.Connection` — opens the file, sets `PRAGMA journal_mode=WAL`, creates `nodes`/`edges` if missing, tries to load `sqlite_vec` and creates `evidence_vec` only if that succeeds. `vec_available(conn) -> bool`. |
| `app/adapters/sqlite_graph_store.py` | `SQLiteGraphStore(db_path)` — `write_graph()` matching `Neo4jGraphStore`'s exact signature/return shape, one transaction per call, `INSERT ... ON CONFLICT DO UPDATE` per node/edge, plus an `evidence_vec` upsert when an Evidence entity carries an embedding and the extension loaded. |
| `app/adapters/sqlite_query_store.py` | `SQLiteQueryStore(db_path)` — `search_evidence()` matching `Neo4jQueryStore`'s exact signature/return shape. Vector path wrapped in try/except, falling back to keyword search on any failure — the same fallback shape `Neo4jQueryStore` already uses. |

## Modified files

- `app/config.py` — `sqlite_db_path: Path = Path("data/graph.db")`.
- `app/adapters/graph_store_factory.py` / `query_store_factory.py` — add an
  `if backend == "sqlite": return SQLite...(db_path=config.sqlite_db_path)`
  branch before the existing neo4j check.
- `requirements.txt` — add `sqlite-vec`. Import is try/except in
  `sqlite_connection.py`, so it's not a hard runtime requirement, just
  ships by default so a normal install gets full functionality.

## Error handling / degradation

- `sqlite-vec` fails to import or load → `evidence_vec` is never created,
  `vec_available()` returns `False`, `search_evidence` skips straight to
  keyword search. No crash, no warning — same silent-degrade posture as the
  existing embedding/MinerU fallbacks elsewhere in this codebase.
- `GRAPH_BACKEND` set to an unsupported value → same
  `GraphStoreFactoryError`/`QueryStoreFactoryError` as today.
- Missing `data/` directory → `connect()` creates parent dirs, matching
  `TaxonomyStore`/`MetadataStore`'s existing pattern.

## Testing

Real SQLite against a `tmp_path` file instead of hand-rolled
`FakeDriver`/`FakeSession`/`FakeRecord` mocks — genuinely simpler than the
Neo4j test setup. Covers: write-then-read roundtrip, `project_id` scoping,
keyword search, vector search when `sqlite-vec` is available, and the
vector→keyword fallback path.
