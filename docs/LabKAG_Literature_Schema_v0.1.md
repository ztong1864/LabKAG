# LabKAG Literature Schema v0.1

## Scope

v0.1 only models literature-level knowledge extracted from papers. It does not
model lab-internal records, author networks, institution networks, research
problem taxonomies, or domain ontology expansion.

## Entity Types

The first version keeps exactly these entity types:

```text
Paper
Method
Material
Condition
Metric
Result
Conclusion
Evidence
```

Deferred entity types:

```text
Author
Institution
ResearchObject
ResearchProblem
```

For v0.1, authors stay as `Paper.authors`, research objects are represented by
`Material`, and research problems are left in `Paper.abstract`, `Result`, or
`Conclusion` text until there is a concrete query need.

## Entity Fields

### Paper

```text
paperId
title
authors
year
journal
doi
abstract
keywords
documentId
```

### Method

```text
methodId
name
description
methodType
```

### Material

```text
materialId
name
type
description
```

### Condition

```text
conditionId
name
value
unit
normalizedValue
normalizedUnit
description
```

### Metric

```text
metricId
name
value
unit
description
```

### Result

```text
resultId
description
value
unit
resultType
```

### Conclusion

```text
conclusionId
description
scope
```

### Evidence

```text
evidenceId
documentId
chunkId
page
sectionTitle
sourceText
offsetStart
offsetEnd
paperId
```

## Relations

```text
Paper proposes Method
Paper uses Material
Paper hasCondition Condition
Paper measures Metric
Paper reports Result
Paper drawsConclusion Conclusion
Paper hasEvidence Evidence

Method supportedBy Evidence
Material supportedBy Evidence
Condition supportedBy Evidence
Metric supportedBy Evidence
Result supportedBy Evidence
Conclusion supportedBy Evidence
```

## Design Notes

The schema is intentionally small. Each extracted fact either belongs directly
to a paper or is supported by evidence from the source text. More specialized
entities should be added only after there is a stable query or downstream
workflow that needs them.

OpenSPG KGDSL requires lowerCamelCase property and relation names. LabKAG's
internal extraction JSON may still use snake_case Pydantic fields; the adapter
owns the mapping into KAG-compatible schema names.
