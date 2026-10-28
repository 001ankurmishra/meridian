# AI v2 intake and baseline evidence — 2026-10-27

**IMPLEMENTED / TESTED:** isolated IBM intake, public-reference ingestion, fixed account-sample diagnostics and maintainer-approved native retrieval baseline. **Stage 2 remains PARTIAL:** native customer-level financial and full graph performance cannot be established from this source/sample. No overall AI accuracy or completion claim.

Branch: `feature/ai-intelligence-v2`; base `af924e539aa228ce3307b9d1fd949c67b261222f`. Local commits only. No runtime model replacement, composite score, LLM API call, demo database change, push or merge.

## Archive and provenance

IBM Dataset A, February 2021, publisher-linked Box archive; data license **CDLA-Sharing-1.0** (separate from repository Apache-2.0). Original download completed and was reused; no duplicate archive download. Source details and comparison with the 2023 release are in `source-comparison.md`.

Archive size: **839,740,068 bytes**. SHA256:
`b58b23154907e95e27a23ec95775cdfaf65ae846d3d4717c611c7d8a45dc8299`.

Full bzip2 decompression/CRC and independently recomputed digest passed. Measured **45,406,931 rows**, all source-format valid: **45,351,508 negative / 55,423 positive** generator labels. IBM publishes 45,351,509 negatives: the measured total is **one row lower**, with no established explanation. No row was invented to reconcile it.

January 1–31, 2019; timezone unspecified. **21,644,001 backward timestamp transitions** confirm input row order is not chronological. Both currency fields contain 15 named currencies; seven payment formats. No blank fields. Source `(null)` amounts: **2,912 received / 513 paid**. Negative amounts: **335,512 paid / 335,512 received** (overlapping row sets; do not add these counts). Their direction semantics are unverified. Preserve these values; affected signals become unknown.

**10 repeated-record excess rows** by SHA256 of exact CSV fields plus label; **zero conflicting-label groups**. These may be distinct business events because no transaction ID exists. Nothing was deduplicated. Duplicate accounting uses disk buckets, not an unbounded in-memory set.

Initial strict-format scans excluded null/signed amounts. The final scan corrected source parsing and preserved all rows; earlier outputs remain local diagnostics and are not final benchmark evidence. Final scan runtime: **497.23 seconds**, peak resident size reported by macOS: **153,780,224 bytes** (see actual receipt for authoritative value).

## Sample, split and leakage controls

Fixed SHA256 seed selects 1% of bank/account pairs, retaining every incident transaction without label-based sampling. **789,860 retained rows: 789,092 negative / 768 positive**. Outgoing selected-anchor pool: **452,534 rows, 290 positive**. This is cluster sampling, not a balanced case-control benchmark. Full-source positive prevalence is about 0.122%; retained incident prevalence is about 0.097%.

Observed graph: **449,924 nodes / 85,139 components**, largest component 1,092 nodes. Entire observed weak components are assigned to DEV or HELDOUT, with fixed temporal target windows and no label-based rebalancing. **27,758 DEV targets (23 positive)** and **91,544 HELDOUT targets (47 positive)**. Earlier history supplies features; no later transaction is used in a score. Amount history excludes timestamp ties, while 24-hour velocity includes ties as in the existing timestamp-level contract.

No observed node or edge crosses component splits. Split construction uses the observed graph only to partition units, not as a predictive feature. Omitted edges among unsampled accounts and absent customer ownership mean full-source graph/customer independence is **not proven**. Scenario IDs are absent; payment format must not be presented as laundering typology. Component-bootstrap uncertainty is conditional on this incomplete observed graph.

Sample SHA256: `f83babca4a2c3d99f6e0f411819b78eed6f59557a3e25c426ed3bc2a890860a8`.
Split assignment SHA256: `d86037c27e2dcc5f0114b8a8d7684bd9ed04867e72f943da696b8fd996b2bd69`.
Protocol SHA256: `7294ecef1c07f785725f54205ab14444553364a46c5a33c41ab308bf0480625d`.

## Measured financial diagnostics

These are **account-unit adaptations**, not executions/validation of the native customer-level SQL. Beneficiary age is not evaluable. Amount history is left-censored relative to a full 90-day window. Signed/missing amounts and currency mismatches are not imputed. Higher-score direction, seed, split, capacity and metrics were locked before performance measurement. Protocol v2.1 documents the source-format amendment before scoring.

| Split / adaptation | Known / unknown | Known positives | ROC-AUC (conditional 95% CI) | Average precision | Precision / recall at 1% capacity | TP / FP |
|---|---:|---:|---|---:|---|---|
| DEV:amount | 20,769 / 6,989 | 14 | 0.547 (0.348–0.667) | 0.002011 | 0.4808% / 7.14% | 1 / 207 |
| DEV:velocity | 27,758 / 0 | 23 | 0.689 (0.594–0.770) | 0.001483 | 0.0000% / 0.00% | 0 / 278 |
| HELDOUT:amount | 65,511 / 26,033 | 34 | 0.603 (0.459–0.727) | 0.010666 | 0.1524% / 2.94% | 1 / 655 |
| HELDOUT:velocity | 88,711 / 2,833 | 47 | 0.679 (0.616–0.747) | 0.001307 | 0.5631% / 10.64% | 5 / 883 |

PR-AUC is step average precision; ROC ties receive half credit. Capacity is ceil(1% of known-score targets), with source-row tie breaks. Recall in the table excludes unknown scores; HELDOUT amount has another **13 positive unknowns**, so its one reviewed positive is only 1/47 of all HELDOUT positives. No risk threshold or classifier was fitted. Full per-currency/per-format results, confusion counts, unknown reasons and 200 fixed-seed component-bootstrap replicates are recorded in `financial-baseline.json`. Runtime: **43.35 seconds**; financial-process peak memory was not captured.

Graph coverage: 1,069 DEV and 2,245 HELDOUT targets have a nonnegative reciprocal-edge witness by their target timestamp. The remaining 26,689 / 89,299 have **unknown longer-path status**, not negative cycle labels. No native four-hop cycle/chain accuracy is claimed. Missing unsampled-node edges and absent as-of support in the native graph schema prevent a faithful full native comparison.

## Public corpus and approved retrieval baseline

**Two published BIS documents, 137 content pages, 494 chunks**, each <=400 pinned-BGE tokens, with source/version/PDF-page metadata. Two blank pages were visually verified. A repeated ingestion reproduced the exact corpus SHA256 `2dedab9e14bc868c6e861b86b3bb5c09fae9e4897d6fa6168cec7c5c1393ffa0`. Full PDFs and chunks stay local for noncommercial research; no public guidance is represented as internal bank policy. FATF/RBI additions remain deferred pending document-specific checks.

Maintainer explicitly approved the 20-query review hash `d6d9a3363545c0cd6c820a3ea2367155860e2152a4d9d06828d55b91e98d1c37`. Freeze record is separate from the immutable review proposal. Labels are **AI-proposed, maintainer-reviewed**, not independently expert-validated.

Native `retrieve_policy_evidence` was executed once for this baseline in application-role temporary tables on the guarded loopback test database. BGE revision, full PostgreSQL lexical/semantic rankings, RRF k=60, top-five output and cosine gate **0.620313** were unchanged.

| Split | Positive passage hits | Positive queries returning any output | Negative abstentions | P@5 | Recall@5 / MRR / nDCG@5 |
|---|---|---|---|---|---|
| DEV | 4/6 | 6/6 | 2/4 | 0.1333 | 0.6667 / 0.6667 / 0.6667 |
| HELDOUT | 4/6 | 6/6 | 2/4 | 0.1333 | 0.6667 / 0.6667 / 0.6667 |

Each positive query has one reviewed gold chunk, so maximum P@5 here is **0.2**, not 1. All 80 returned citation IDs/text hashes were mechanically valid. For positive queries, source/version agreement was 24/30 DEV and 21/30 HELDOUT; that does not establish passage support or domestic applicability. Only three positive topic families per split make generalization intervals **not estimable**.

Failure examples: both alert-assessment DEV paraphrases missed the supporting passage; both correspondent-banking HELDOUT queries missed the reviewed chunk. Unsupported bank-specific rupee thresholds and original-2012-source requests were retrieved. The contradictory ten-year retention premise also passed the gate. Results expose limitations; no threshold, labels, corpus or seed were changed after scoring.

Embedding: **9.34 seconds**; measured corpus embedding plus queries: **10.40 seconds** (model load excluded). API cost **$0**, no paid calls. Retrieval memory peak was not captured. No generated-answer faithfulness or single overall AI accuracy is claimed.

## Verification and remaining work

- 38 focused offline tests passed before final integration; the 105-test guarded integration set includes those plus existing retrieval, ordering, gate, evaluation and database-guard tests: **105 passed in 6.04 seconds**.
- Four additional reference-download safety tests passed; the financial/reference focused recheck passed 12 tests. Final offline recheck: **43 passed**. Repository-wide Ruff and mypy (103 source files) passed again after the final reader change.
- Repository-wide Ruff passed; mypy passed **103 source files**. Only `pypdf==6.21.2` was added to dev dependencies; existing locked versions were unchanged. Targeted pip-audit found no known pypdf vulnerabilities.
- v1 frozen evidence, accepted ADRs, runtime model configuration and demo database remain unchanged. Full suite was not repeated; Docker deployment/browser verification was not performed for this branch.
- Native customer/beneficiary and full graph measurements remain blocked by source/adapter limitations. Independent expert label review, broader policy applicability labels, RBI/FATF coverage and representative long-history financial data remain outstanding.
- Current evidence does not justify replacing the runtime model, calibrating thresholds or adding composite scores. Future embedding/reranking comparisons must use DEV for selection and separately lock final measurement, preserving all recorded HELDOUT evidence.

Implementation commits: `d40e910`, `6f95f49`, `f242e0d`, `febc024`, `bd520a3`, `0ad41e7`. Final evidence/docs are committed separately. See `changed-files.txt` and `REPRODUCE.md`.
