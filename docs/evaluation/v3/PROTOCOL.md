# Stage 3 DEV comparison — protocol 1 (2026-10-27)

Status: PROPOSED machine-authored relevance judgments. DEV experimentation only.
No independent final validation set exists. Neither prior v1 nor v2 HELDOUT
outputs are inputs to selection. All 48 new queries are DEV; related paraphrases
remain in one family. No claim of an untouched test split or independent review.
The corpus is the unchanged, licensed local 494-chunk BIS corpus from v2.

## Comparisons and selection rules

A: preserve existing pinned small embedding + complete PostgreSQL English FTS
and exact pgvector ranking + RRF k=60, top five, RRF minimum 0.01 and ADR-0009
query cosine gate 0.620313. A separate DEV-fitted gate is an ablation, not A.
B: pinned base embedding, identical ranking, with its own DEV-only query gate.
C: best DEV embedder by ungated mean positive nDCG@5 (ties choose small), rerank the
first 50 fused candidates using pinned bge-reranker-base. Report first-stage
candidate recall separately from top-five quality. Do not prefilter these
candidates with a gate before reranking. Query/passage reranker-score filtering
is an explicit ablation. No BGE-large download until results justify it.

Fit each exploratory gate to maximize balanced positive acceptance and negative
abstention on DEV; ties use the higher threshold. Report both ungated retrieval
and fitted-gate results so the trade-off is visible. Fitting and reporting on
the same DEV data is optimistic and is not independent evaluation/calibration.
No probability interpretation of cosine or reranker logits. A query-level gate
does not certify every passage. Metadata eligibility must use query/source
metadata, never gold labels or an expectation oracle.

## Labels and metrics

`dev-proposals.json` includes query IDs, families, graded passage labels,
abstention expectations, applicability and rationales. Grades 3=direct support,
2=substantial partial support, 1=context only, 0=unjudged/no support. Binary
relevance is >=2. All judgments are provisional and non-exhaustive: unjudged
valid alternatives can be penalized. P@5 has denominator five even with fewer
than five relevant labels; include relevant-passage counts. nDCG uses gains
2^grade-1, MRR is truncated at five, and candidate recall precedes filtering.

A request to endorse a false claim is a negative, even when a passage can refute
it. A question asking whether a practice is permitted can be positive with a
corrective passage. This benchmark evaluates supporting-passage retrieval,
not answer generation or whether a model can explain the contradiction.

Report positive Hit@1, Recall@5, P@5, MRR@5, nDCG@5 and candidate recall;
negative abstention and false retrieval; mechanically valid citations and
source/version eligibility separately from semantic claim support. Use paired
family bootstrap for descriptive DEV uncertainty, with fixed seed 20261027,
1,000 replicates. This reflects sampling of proposed families only, not label
uncertainty, generalization or domestic applicability. Report all denominators.

## Reproducibility and safety

`models.json` pins weights and tokenizer revisions and records publisher license
metadata and weight sizes. Model cards specify query instruction on embeddings,
no passage instruction, normalized embeddings, and paired raw query/passage
inputs for the cross-encoder. Use CPU float32, deterministic ordering, fixed
thread count and identical corpus/query order. Verify actual token lengths and
report any truncation. No remote code or pickle model weights are permitted.

Cache model-specific vectors and reranker scores keyed by corpus, queries,
model/tokenizer revision and preprocessing. Record cache hits separately from
measured inference. Measure cold model loading separately from document/query
encoding and warmed query retrieval/reranking. Capture process peak RSS with
platform units, hardware, thread count and library versions. Keep outputs
immutable, with configuration/protocol hashes before inference. Experiment
artifacts live separately from frozen v1/v2 files. Raw PDFs, chunks, model
weights and caches remain ignored local files. Guarded disposable DB and TEMP
relations only; no runtime embeddings, model settings or accepted ADR changes.

Independent final validation remains BLOCKED until an untouched independently
reviewed set is available. Stage 3 can produce DEV research evidence meanwhile.
Runtime adoption requires maintainer review of ADR-0004/0009, new vector storage
for 768 dimensions if selected, reproducible re-embedding and rollback, and
measured CPU/memory/deployment implications. No adoption is authorized here.
