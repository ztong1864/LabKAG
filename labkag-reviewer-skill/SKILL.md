---
name: labkag-skill
description: "API wrapper skill for LabKAG. Use when an agent needs to call the LabKAG HTTP API through the bundled CLI script for health checks, upload, extraction, ingestion, literature query, evidence search, knowledge inspection, taxonomy management, or topic-based paper discovery."
---

# LabKAG API Wrapper

Use this skill when you need to call LabKAG as an external service.
Do not modify the LabKAG repository.

This skill folder lives inside the LabKAG project itself
(`labkag-reviewer-skill/`) — it is self-contained and should not be confused
with any other `labkag-skill`-named folder elsewhere on disk. All paths
below are relative to this project's root.

## Call Pattern

Prefer the bundled script:

```text
py -3.10 labkag-reviewer-skill/scripts/labkag_api.py <command> [args]
```

Default base URL:

```text
http://127.0.0.1:8001
```

Override with `--base-url` or `LABKAG_BASE_URL`.

## Commands

- `health`
- `upload --file <pdf>`
- `extract --file-id <id> [--project-id <id>] [--extract-level basic|detailed] [--return-chunks] [--use-backup]`
- `ingest --paper-extraction <json-file> [--project-id <id>] [--confirm]`
- `query --question <text> [--project-id <id>] [--paper-id <id>] [--top-k N]`
- `search --query <text> [--project-id <id>] [--paper-id <id>] [--top-k N]`
- `knowledge --paper-id <id> [--project-id <id>] [--include-evidence / --no-include-evidence]`
- `papers-list --project-id <id>`
- `taxonomy-get --project-id <id>`
- `taxonomy-set --project-id <id> --taxonomy <json-file> [--confirm]`
- `match-topic --project-id <id> --plan <json-file> [--min-essential-signals N] [--no-borderline] [--limit N]`

## Minimal Rules

- Call `health` before other actions when the service state is unknown.
- Use `upload -> extract -> ingest -> query/search/knowledge` for the literature pipeline.
- Treat non-2xx responses as service failures and inspect the returned JSON body.
- `extract` requires the configured LLM provider. `--use-backup` reads the PyMuPDF
  fallback (`data/parsed_backup/`) instead of MinerU output for that file.
- `ingest` writes to Neo4j only when `--confirm` is set.
- `search` and `query` should prefer embedding when the service is configured for it.

## Topic Discovery & Taxonomy

**The LabKAG backend never calls an LLM at query time.** Retrieval — vector
search, graph traversal, corroboration scoring — is deterministic. Any step
that requires understanding a topic or judging what a domain's useful
categories are happens here, in you, before you call the backend. The
backend only validates what you send it and executes the match.

Workflow to find papers matching a topic:

1. `taxonomy-get --project-id <id>`. If it returns nothing and the project
   already has extracted papers, follow
   `references/taxonomy_bootstrap_prompt.md` to propose one, then
   `taxonomy-set` it.
2. Follow `references/topic_decomposition_prompt.md` to turn the topic into
   a `topic_plan.json` file, using the taxonomy from step 1.
3. `match-topic --project-id <id> --plan topic_plan.json`.
4. Report `confirmed` and `borderline` results separately — never merge
   them. A `confirmed` result cleared a two-signal corroboration bar; a
   `borderline` result cleared only one and needs further judgment before
   being treated as a real match. Never pad a small `confirmed` set with
   `borderline` results to hit a target count — say how many were found and
   why, instead. Relay each result's `reasons` entries to the user
   **verbatim** rather than re-deriving your own explanation — the backend
   already produces a human-readable reason per match (e.g. citing shared
   evidence for a co-occurrence hit), and re-paraphrasing risks
   misrepresenting *why* something was confirmed. A small or empty
   `confirmed` list is an expected, correct outcome when the corpus
   genuinely lacks papers combining the topic's essential concepts together
   — do not treat it as a bug to work around by loosening
   `--min-essential-signals` without telling the user why.

These two reference docs are the LLM-to-backend contract boundary. Do not
skip their verification rules (never invent a taxonomy category/value that
doesn't exist, never submit a plan with zero essential concepts, compute the
year filter correctly yourself) — the backend enforces them, and a plan that
violates them is rejected rather than silently corrected.

### Error-code remediation

- `TAXONOMY_NOT_CONFIGURED` — no taxonomy exists for this project yet. Run
  `references/taxonomy_bootstrap_prompt.md`'s flow before attempting any
  topic decomposition for it.
- `TOPIC_UNRESOLVED` — the submitted plan had zero essential concepts. Read
  the `unresolved` list in the error detail and either resolve it using the
  project's taxonomy or ask the user to clarify the topic. Never resubmit
  with a guessed concept.
- `GRAPH_QUERY_FAILED` — a backend/Neo4j failure, not a problem with your
  plan. Treat it like any other 5xx service failure.
- `POST /v1/projects/{id}/taxonomy` can return `status: "needs_review"`
  (not an error) with `applied: false` and `affected_papers_count` — this
  means the edit is breaking (removes/renames a value already in use). Read
  the count, decide whether to proceed, then resubmit with `--confirm` if
  so. Never pass `--confirm` reflexively on every call — it should follow a
  deliberate read of `affected_papers_count`.

## Output Handling

- Print or return the raw JSON response when possible.
- If the API returns a structured error body, surface the `status`, first error `code`, and message.
- Do not infer success from HTTP status alone; inspect the JSON payload.
