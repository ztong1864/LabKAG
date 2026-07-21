# Taxonomy Bootstrap Prompt

A project's taxonomy (its controlled categories and allowed values) is what
makes topic matching precise instead of noisy. The LabKAG backend never
proposes one itself — that is a judgment call about the domain, made here by
you (the agent), not a mechanical build step. The backend only stores and
validates whatever taxonomy you submit.

Use this when `taxonomy-get --project-id <id>` returns nothing for a project
that already has extracted papers, and someone wants topic matching to work
for it.

## Process

1. List the project's papers: `papers-list --project-id <id>`.
2. Read a representative sample (10-20 papers is usually enough; more for a
   project spanning several sub-domains) via
   `knowledge --paper-id <id> --project-id <id>`. Look at the free-text
   `methods`, `materials`, `conditions`, `metrics`, `results`, and
   `conclusions` fields already extracted for each paper.
3. Infer 3-6 categories that would actually distinguish these papers from
   each other for retrieval purposes — not generic bibliographic fields
   (title/journal/year already exist separately), but the domain-specific
   axes a researcher would search by. For a chemistry corpus this is
   typically something like catalyst/reagent class, substrate class, and
   reaction type; for a different domain the axes will be different. Do not
   copy a fixed category list from another project — derive it from what is
   actually in these papers.
4. For each category, enumerate the allowed values that actually appear
   across the sampled papers (plus close variants worth merging as aliases,
   e.g. "Fe(NO3)3", "iron nitrate", "ferric nitrate" as aliases of one
   canonical value "iron"). Do not invent values that were not observed.
5. Write the taxonomy to a local JSON file and submit it:

```text
py -3.10 labkag-reviewer-skill/scripts/labkag_api.py taxonomy-set \
  --project-id <id> --taxonomy taxonomy.json
```

If a taxonomy already exists for the project and this is an edit rather than
a first-time bootstrap, submitting a change that removes or renames an
existing value is a breaking change. `taxonomy-set` will report
`affected_papers_count` without applying the change unless you pass
`--confirm`. Always look at that count before confirming — a large number
means many already-tagged papers will need retagging, which is a real cost,
not a formality.

## Rules

- Keep the category count small (3-6). A taxonomy with too many categories
  makes topic decomposition ambiguous and dilutes the corroboration signal
  the matcher relies on (two matched categories should mean something).
- Prefer values that are specific enough to be useful but broad enough to
  recur across multiple papers — a value only one paper in the whole corpus
  would ever match is not a useful retrieval axis.
- Do not add a "document_scope" or similar generic category unless the
  project genuinely mixes document types (e.g. primary research vs. review
  vs. patent) in a way that matters for retrieval.
- `essential_by_default` on a category is a hint for topic decomposition
  (`topic_decomposition_prompt.md`), not a hard rule — the decomposer marks
  essential/supporting per-topic, not per-category. Set it for whichever
  reading is right most of the time for this category.

## Expected `taxonomy.json` shape

```json
{
  "project_id": "proj_123",
  "categories": [
    {
      "key": "catalyst_type",
      "description": "The primary catalyst or catalytic metal used.",
      "allowed_values": ["iron", "copper", "palladium", "gold"],
      "aliases": {
        "iron": ["Fe(NO3)3", "iron nitrate", "ferric nitrate", "Fe"]
      },
      "essential_by_default": true
    },
    {
      "key": "reaction_type",
      "description": "The core transformation the paper reports.",
      "allowed_values": ["aerobic_oxidation", "cross_coupling", "cyclization"],
      "aliases": {},
      "essential_by_default": true
    }
  ]
}
```
