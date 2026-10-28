# Runtime adoption decision requirements — Stage 3

Status: REVIEW MATERIAL ONLY. No accepted ADR is changed by these experiments.
Current runtime remains pinned BGE-small, vector(384), PostgreSQL English FTS,
complete exact semantic ranking, RRF k=60 and ADR-0009 cosine gate 0.620313.

## Options and approval boundaries

1. **Retain runtime.** No migration or ADR amendment. This is the default while
   evidence consists of proposed DEV labels and no independent final validation.
2. **Small with a revised query gate.** No schema migration, but ADR-0009 must
   explicitly approve the new threshold, selection objective, validation evidence
   and rollback. The 0.7208284354456796 DEV fit is not a calibrated probability.
3. **Base embedder.** ADR-0004 must approve the model/revision, tokenizer,
   preprocessing and 768 dimensions; ADR-0009 needs a separately validated gate.
   Do not cast or overwrite current 384-dimensional vectors. A separate versioned
   embedding column/table and complete validated re-embedding would be needed,
   followed by an explicit cutover and retained small-model rollback path.
   No migration is proposed for implementation now: measured DEV ranking does
   not justify this extra storage and operational complexity.
4. **Cross-encoder reranking or passage/source filters.** Approval must define
   candidate depth, ordering/tie rules, score semantics, abstention and failure
   behavior. Preserve reproducible first-stage evidence and distinguish original
   ranks from reranked citations. No embedding schema migration is inherently
   required when small remains the embedder. An unavailable or failed reranker
   must not silently bypass an approved abstention contract; the approved policy
   must specify controlled abstention versus an explicitly labeled fallback.

## Evidence required before adoption

Have an independent reviewer create an untouched set of source-grounded queries
and passage judgments, with applicability and contradiction cases. Keep it out
of DEV selection. Reviewing these already-used 48 DEV queries cannot turn them
into an untouched final set. Lock one candidate configuration and all score
thresholds before testing; do not retune after seeing final outcomes.

Use failure cases beyond literal years/country names and varied question styles.
The experimental explicit-source regex rules are not a legal-applicability
engine. Cross-encoder relevance is not textual entailment, and mechanically
valid citation IDs do not prove statement support. No answer-generation model
or AML decision-making capability is evaluated in this stage.

For deployment, pin model/tokenizer revisions and verify safetensors checksums;
cache approved artifacts before network-isolated startup. Measure process and
concurrent-request memory, warm/cold latency and CPU saturation in the intended
container. Set bounded request timeouts and batch/concurrency limits, and verify
fresh image/startup and browser workflow after any approved runtime change.
Current local process RSS measurements are not a Docker verification or capacity
SLA. No paid service, LLM API, new runtime dependency or deployment is authorized.

## Stage continuity

After Stage 3 review, request approval before Stage 4 financial/graph work.
Optional Stage 5 external LLM usage requires its own provider/privacy/cost and
ADR-0003 approval. Stages 6 and 7 must follow stable interfaces and explicit scope.
Do not interpret this decision note as approval for any later stage.
