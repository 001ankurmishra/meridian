# Stage 3 review — 2026-10-27

**Status: PARTIAL — experimental comparison COMPLETE; independent final validation BLOCKED.**
**Recommendation: retain the pinned BGE-small runtime without reranking.** A revised
query gate is a DEV research candidate only; no runtime threshold or model was changed.

## Exact evaluation identity

`meridian-rag-v3-dev-1`, 48 AI-authored **PROPOSED** labels: 24 positive queries
in 12 paraphrase families and 24 negatives. Canonical label SHA256:
`8554947d70022080cf4dddcbc3cbb57167f7932b3555689ef5af1a775e17550e`.
The unchanged v2 corpus contains 494 chunks from two licensed BIS references.
All positive targets concern the 2020 AML guidance; the 2024 Core Principles
provides competing passages. Generalization to the full corpus is unproven.
There is no untouched independently reviewed final set. Existing v1/v2 frozen
evidence and runtime retrieval were preserved; no HELDOUT measurement occurred.

Grades >=2 count as relevant, with 31 query/passage associations. Judgments are
non-exhaustive; valid unlabeled alternatives can be penalized. The average
P@5 ceiling here is 31/120 = .2583. nDCG includes graded gains. All threshold
fits and reported gains below use the same DEV data and are optimistic.

## Measured comparison

Each row has 24 positive and 24 negative queries. Neg abstain is a count; false
retrieval rate is its complement divided by 24. Candidate recall at depth 50
is 1.0 for both embedders and therefore for the reranker input.

| Configuration | Hit@1 | Recall@5 | P@5 | MRR@5 | nDCG@5 | Neg abstain | False retrieval |
|---|---:|---:|---:|---:|---:|---:|---:|
| bge-small-en-v1.5/original_gate | 0.667 | 0.854 | 0.208 | 0.767 | 0.768 | 8/24 | 0.667 |
| bge-small-en-v1.5/ungated | 0.667 | 0.854 | 0.208 | 0.767 | 0.768 | 0/24 | 1.000 |
| bge-small-en-v1.5/dev_query_gate | 0.667 | 0.854 | 0.208 | 0.767 | 0.768 | 22/24 | 0.083 |
| bge-small-en-v1.5/dev_passage_gate | 0.667 | 0.667 | 0.158 | 0.701 | 0.663 | 22/24 | 0.083 |
| bge-small-en-v1.5/dev_passage_eligibility | 0.667 | 0.667 | 0.158 | 0.701 | 0.663 | 23/24 | 0.042 |
| bge-base-en-v1.5/ungated | 0.583 | 0.875 | 0.217 | 0.705 | 0.726 | 0/24 | 1.000 |
| bge-base-en-v1.5/dev_query_gate | 0.583 | 0.875 | 0.217 | 0.705 | 0.726 | 23/24 | 0.042 |
| bge-base-en-v1.5/dev_passage_gate | 0.583 | 0.792 | 0.192 | 0.694 | 0.691 | 23/24 | 0.042 |
| bge-base-en-v1.5/dev_passage_eligibility | 0.583 | 0.792 | 0.192 | 0.694 | 0.691 | 24/24 | 0.000 |
| bge-reranker-base/ungated | 0.333 | 0.667 | 0.167 | 0.514 | 0.542 | 0/24 | 1.000 |
| bge-reranker-base/dev_query_gate | 0.250 | 0.542 | 0.133 | 0.410 | 0.432 | 22/24 | 0.083 |
| bge-reranker-base/dev_passage_gate | 0.250 | 0.417 | 0.100 | 0.368 | 0.368 | 22/24 | 0.083 |
| bge-reranker-base/dev_passage_eligibility | 0.250 | 0.417 | 0.100 | 0.368 | 0.368 | 23/24 | 0.042 |

Gate fits maximize balanced positive acceptance and negative abstention,
with conservative ties. Small threshold: 0.7208284354456796; base:
0.6633880138397217; reranker raw logit: 0.7102761268615723. These are neither
calibrated probabilities nor approved replacements for ADR-0009. Passage
filtering reuses the query threshold as a disclosed ablation, not a separately
optimized passage threshold. Explicit-source rules inspect text only, not labels.

Small was selected for reranking by the predefined highest ungated DEV nDCG
rule. Reranking all 50 candidates lowers ungated nDCG by .2263; a descriptive
paired-family bootstrap 95% interval is [-.3912, -.0663]. Base-minus-small
ungated nDCG delta is -.0417 with interval [-.1900, .0946]. These intervals do
not incorporate label uncertainty or selection bias. Negative families are
singletons and may still be correlated by category. See JSON for all intervals.

## Resource measurements

Apple M4, 10 logical CPUs, 16 GiB RAM; CPU float32, four inference threads.
All model weights passed published SHA256/size checks. Exact model/tokenizer
revisions and publisher MIT license metadata are in `models.json`. No paid API
calls, LLM calls or new dependency. All measured runs had zero truncations.

| Model | Construction/load s | Corpus embedding s | Warm mean / p95 ms | Process peak GiB |
|---|---:|---:|---:|---:|
| bge-small-en-v1.5 | 0.106 | 7.778 | 44.84 / 48.11 | 1.055 |
| bge-base-en-v1.5 | 0.110 | 19.729 | 51.12 / 52.99 | 1.899 |
| bge-reranker-base | 0.961 | 0.000 | 2280.09 / 2609.21 | 1.722 |

Reranker timing is **additional** to first-stage retrieval: combined cached
per-query timing observations average 2.325 seconds (p95 2.650 seconds), versus
44.84 ms for small alone. This sum combines separately measured runs; it is
not a live combined-service load test. Reranker RSS likewise excludes a
co-resident embedder. Model load excludes imports/download and mmap page faults
may occur later. Process peak RSS includes libraries and batches. No Docker
deployment or browser verification is claimed.

## Failures and evidence limits

- Original small gate retrieves for 16/24 negatives. The DEV-fitted small gate
  still retrieves for a nonexistent 2025 edition and a universally mandated
  monitoring-software request. Base still retrieves for that absent edition.
- Reranker query gating abstains on four positive queries and leaves two false
  retrievals. Its ungated source/version match falls to 82/120 positive citations,
  versus small 113/120 and base 114/120. These are metadata checks, not entailment.
- For `dev-record_updates-1`, reranking promotes a Core Principles supervisory
  review passage over the proposed CDD-record-update passage. Direct pinned
  AutoModelForSequenceClassification inference reproduces both cached scores
  within 1e-4, recorded in `reranker-inference-parity.json`. This checks the
  scoring wrapper on two pairs; it is not an independent label review.
- Passage filtering loses supporting evidence for all tested models. Explicit
  source rules improve some negative counts but can over-abstain on historical
  comparison questions. They do not establish jurisdictional applicability.
- Candidate IDs refer to the fixed hashed corpus, but mechanical identity does
  not prove relevance or support. No generated-answer faithfulness was tested.
- The first reranker download failed during a transient DNS/CDN interruption.
  One cache-reusing retry succeeded; no duplicate active download was launched.
  The parity diagnostic initially requested a complete offline Hub snapshot,
  including deliberately excluded ONNX files; retrying with the same safe-file
  allowlist succeeded without additional downloads.

## Verification and adoption decision

Guarded integration checkpoint: **98 passed in 5.49 seconds**. Repository-wide
Ruff and mypy (106 source files) passed. A subsequent correction removed the
hidden RRF cutoff after reranking, before reranker results were available:
**27 targeted offline tests** and scoped Ruff/mypy passed. No full-suite repeat.
Native parity verifies lexical/semantic fusion ordering and cosine maxima;
768-dimensional storage remains isolated in temporary test-database tables.
The amendment and rule hashes are recorded transparently in `experiment-lock.json`.

Retain the simpler small model. No BGE-large experiment is justified by these
results. Further tuning on these same labels would not establish a verified
improvement. Obtain an independently authored, untouched final set before
considering runtime gate changes. Approval boundaries, ADR-0004/0009 implications,
768-dimensional migration options, failure behavior and deployment checks are
in `runtime-review.md`. No migration or accepted ADR was changed.

Implementation commits: `1405ba2`, `56c0783`, `f4fa4a0`, `708baa2`; final evidence
is committed separately. `changed-files.txt` lists the complete Stage 3 scope.
Next task: independent final-set construction and review. Stage 4 and later
stages require maintainer approval and were not started.

**STAGE 3 REVIEW READY — NO RUNTIME MODEL CHANGE APPLIED**
