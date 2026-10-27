# Stage 3 embedding checkpoint — 2026-10-27

Status: PARTIAL. Embedding comparison measured; reranking is not yet measured.
No runtime change, push, deployment or final-validation claim.

## Evaluation identity and limits

`meridian-rag-v3-dev-1`, canonical label hash
`8554947d70022080cf4dddcbc3cbb57167f7932b3555689ef5af1a775e17550e`.
48 proposed AI-authored DEV queries: 24 positives across 12 paraphrase families,
24 negatives. These are not independently reviewed labels. All positive targets
are from the 2020 AML document; the 2024 Core Principles also provides competing
passages. This is a narrow retrieval diagnostic, not coverage of all BIS topics.
There are 31 query-to-relevant-passage associations; judgments are not exhaustive.
The average theoretical P@5 ceiling from these labels is 31/120 = 0.2583.
No previously inspected HELDOUT results were used for threshold/model selection.

## Measured comparison

Each row has 24 positive and 24 negative queries. Gates marked DEV are fitted
and scored on the same data; their apparent abstention gains are optimistic.

| Configuration | Hit@1 | Recall@5 | P@5 | MRR@5 | nDCG@5 | Negative abstentions | False retrieval rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Small, original ADR-0009 gate | .667 | .854 | .208 | .767 | .768 | 8/24 | .667 |
| Small, DEV query gate | .667 | .854 | .208 | .767 | .768 | 22/24 | .083 |
| Base, DEV query gate | .583 | .875 | .217 | .705 | .726 | 23/24 | .042 |

Both ungated models have 100% labeled candidate recall at depth 50, and retrieve
for every negative. Small's fitted query threshold is 0.7208284354456796;
base's is 0.6633880138397217. Neither is calibrated or approved for runtime.
Both fitted query gates retain all 24 positive outputs on this DEV set.

Passage filtering with the query-fitted threshold reduces small nDCG to .663
and base to .691. Adding explicit-source eligibility reaches 23/24 and 24/24
negative abstentions respectively, but does not restore lost relevant passages.
These rules do not prove applicability or entailment and can over-abstain.

Source/version eligibility on positive citations is 113/120 small and 114/120
base with query gating. This checks metadata only, not statement support.
Base-minus-original nDCG delta is -0.0417, with descriptive paired-family
bootstrap 95% interval [-0.1900, 0.0946]. This does not establish a model winner
beyond the selection rule. Bootstrap intervals exclude label uncertainty and
model-selection bias; negative families are singleton proposals and may remain
correlated by category. Full metrics and query IDs are in the comparison JSON.

## CPU resources

Apple M4, 10 logical CPUs, 16 GiB physical memory; inference uses four threads,
float32, identical 494-chunk corpus. Model and tokenizer revisions/licenses are
in `models.json`. Both embedding runs had zero input truncations.

| Model | Model construction/load | Corpus embedding | Warm query mean / p95 | Process peak RSS |
|---|---:|---:|---:|---:|
| Small | .106 s | 7.778 s | 44.84 / 48.11 ms | 1.056 GiB |
| Base | .110 s | 19.729 s | 51.12 / 52.99 ms | 1.899 GiB |

Model load excludes library imports/download; mapped weights can fault during
inference. RSS is lifetime process high-water, not model size. These are local
single-process measurements, not deployment capacity estimates.

## Selection, regressions and next step

The predefined highest-ungated-nDCG rule selects **small** for reranking its
50-candidate pool. Base is heavier and has weaker first-result/ranked quality
here, despite slightly higher recall. No BGE-large experiment is justified.

Small still falsely retrieves for the nonexistent 2025 Core Principles edition
and the universally mandated monitoring software request after query gating.
Base still retrieves for that nonexistent edition. Partial evidence misses
include risk-factor and internal-audit questions. Passage filtering discards
some labeled supporting passages. These failures are not fixed by valid IDs.

The pinned reranker download encountered DNS failures and remained active at
this checkpoint; no reranker score or completed-download claim is made. Preserve
its cache and inspect the existing process before retrying. Independent final
validation is BLOCKED until an untouched independently reviewed set exists.

Tests: 26 new offline tests and two guarded parity/isolation tests passed.
The broader guarded checkpoint includes these tests and existing retrieval,
gate, frozen-evidence and DB-guard tests: **98 passed in 5.49 seconds**.
Repository-wide Ruff and mypy (106 source files) passed. Full suite not repeated.
The native ranking parity test validates FTS/RRF ordering and cosine maxima;
the 768-dimensional test validates isolated temporary storage. No demo DB writes.

Implementation commits: `1405ba2`, `56c0783`; checkpoint evidence committed
separately. See `REPRODUCE.md`, `experiment-lock.json`, `verification.json`.
