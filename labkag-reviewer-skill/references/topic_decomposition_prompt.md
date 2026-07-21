# Topic Decomposition Prompt

The LabKAG backend never calls an LLM to understand a topic. That reasoning
happens here, in you (the agent running this skill), before you ever call
`match-topic`. The backend only validates the plan you produce and executes a
deterministic graph/embedding match against it.

Given a free-text topic and a project's current taxonomy (fetch it first with
`taxonomy-get --project-id <id>`), resolve the topic into a structured
`TopicPlan` and save it to a local JSON file. That file is the
agent-to-backend boundary, passed to `match-topic --plan <path>`.

## Rules

- Every `concept.category` must be one of the taxonomy's declared category
  `key` values. Every `concept.value` must be one of that category's
  `allowed_values` (or a value covered by its `aliases`). Never invent a
  category or value that is not in the taxonomy — if the topic implies
  something the taxonomy does not cover, put it in `unresolved` instead of
  guessing or picking the closest existing value.
- Mark each concept `essential: true` only if the topic is not meaningfully
  about the paper without it. Mark it `essential: false` (supporting) if it
  narrows or contextualizes the topic but a paper missing it could still be
  relevant. Do not mark everything essential — the backend will reject a
  paper that only matches supporting concepts, so under-marking essential
  concepts silently loses recall, and over-marking it turns a broad review
  topic into a narrow one that returns almost nothing.
- Give every concept a calibrated `confidence` (0-1) and a short `reason`
  tied to the actual topic wording, not a generic justification.
- Compute `year_from`/`year_to` yourself from any relative-year phrase in the
  topic (e.g. "past five years" against the current calendar year, inclusive
  range). The backend independently re-derives this from the raw topic text
  and rejects the plan if your stated range disagrees — so compute it
  correctly, do not leave it to the backend to fix.
- If the topic contains an abbreviation or term ambiguous enough that mapping
  it to a taxonomy value would be a guess, add it to `unresolved` with a
  `reason` instead. A plan may still proceed if other concepts give it a
  meaningful search. A plan with no essential concepts at all must not be
  submitted — stop and ask the user to clarify the topic first.
- Prefer more specific, narrower matches to more general ones when the
  taxonomy offers both (e.g. a specific allowed value over a broad
  catch-all), since specificity is what makes the backend's corroboration
  scoring precise instead of noisy.

## Expected `topic_plan.json` shape

```json
{
  "topic": "Iron-catalyzed aerobic oxidation of primary alcohols in the past 5 years",
  "project_id": "proj_123",
  "concepts": [
    {
      "category": "catalyst_type",
      "value": "iron",
      "essential": true,
      "confidence": 0.95,
      "reason": "Topic explicitly names iron catalysis."
    },
    {
      "category": "reaction_type",
      "value": "aerobic_oxidation",
      "essential": true,
      "confidence": 0.9,
      "reason": "Topic explicitly names aerobic oxidation."
    },
    {
      "category": "substrate_class",
      "value": "primary_alcohol",
      "essential": false,
      "confidence": 0.8,
      "reason": "Narrows the topic but iron/aerobic-oxidation papers on other alcohol classes may still be relevant."
    }
  ],
  "unresolved": [],
  "year_from": 2021,
  "year_to": 2026
}
```

## Usage

```text
py -3.10 labkag-reviewer-skill/scripts/labkag_api.py taxonomy-get --project-id <id>
```

Read the returned taxonomy, write `topic_plan.json` following the rules
above, then:

```text
py -3.10 labkag-reviewer-skill/scripts/labkag_api.py match-topic \
  --project-id <id> --plan topic_plan.json
```

The response separates `confirmed` and `borderline` papers. Never merge them
into one list when reporting results to the user — the tier distinction is
the whole point of the corroboration model: a `confirmed` result cleared a
two-signal bar, a `borderline` result only cleared one and needs a human (or
your own further judgment) before being treated as a real match.
