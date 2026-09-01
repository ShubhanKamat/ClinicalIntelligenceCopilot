Decision 1: Restrict initial scope to obesity/overweight.
Reason: Keeps the corpus coherent and evaluation tractable.

Decision 2: Start with four competitors.
Reason: Enough competitive diversity without making a weekend project too large.

Decision 3: ClinicalTrials.gov is the canonical trial source.
Reason: Structured, authoritative trial records suitable for both SQL-style querying and retrieval.

Decision 4: Do not use RAG for every question.
Reason: Counts, filters and aggregations should come from structured data; RAG is for narrative evidence.

Decision 5: No multi-agent architecture initially.
Reason: Tool calling + retrieval is sufficient for the actual decision problem.