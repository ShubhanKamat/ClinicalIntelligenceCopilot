Project:
Evidence-Grounded Obesity Drug Competitive Intelligence Copilot

Primary user:
Pharma competitive-intelligence / strategy analyst

Business problem:
Compare obesity-drug development pipelines across competitors and
synthesize the clinical-trial evidence supporting those comparisons.

Decision supported:
Help analysts identify how competitor pipelines differ by development
stage, intervention, trial design, endpoints, population and program
progression.

Companies:
- Novo Nordisk
- Eli Lilly
- Amgen
- Boehringer Ingelheim

Scope:
- Obesity / overweight
- Interventional trials
- Primarily Phase 2, Phase 2/3 and Phase 3
- Ongoing and completed studies

Primary source:
ClinicalTrials.gov

Secondary source:
FDA/openFDA for approved-product evidence where relevant

Supported question types:
- factual
- comparative
- multi-trial analytical
- evidence synthesis

Explicit non-goals:
- predict trial success
- predict regulatory approval
- medical advice
- market-share/revenue forecasting
- claim cross-trial efficacy superiority without appropriate evidence

System principle:
Structured questions should use structured trial data.
Narrative questions should use retrieval.
LLM synthesis must remain grounded in cited evidence.

Evaluation objectives:
- Recall@5 / Recall@10 / MRR
- answer correctness
- citation correctness
- groundedness
- abstention accuracy
- structured-output validity
- latency and cost