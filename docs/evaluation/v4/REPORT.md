# Stage 4 review — 2026-10-27

**IMPLEMENTED / TESTED / MEASURED: DEV research milestone complete.**
No runtime adoption is recommended yet. The observed improvements are small,
uncertain and insufficient to claim materially lower false-positive burden.

## Scope and provenance

Eight deterministic candidates plus two unchanged baselines were evaluated on
27,758 existing DEV targets with 23 IBM generator-positive labels. Definitions
and directions were committed in `b14cacf` before measurement. The sample,
component assignment and DEV window remain unchanged; original archive, Stage 2
HELDOUT and all Stage 3 evidence were preserved. Both recomputed DEV baselines
exactly match the recorded v2 known/unknown counts, AUC/AP and capacity TP/FP.

These are bank/account adaptations, not native customer-level validation.
IBM labels indicate synthetic illicit-origin funds, not legal AML determinations.
No KYC, ownership, beneficiary date, typology or source-of-funds tracing was invented.
No composite score, fitted threshold, model, UI, LLM or deployment change.

## Existing versus proposed performance

ROC-AUC and AP use each feature known-score population, which differs by feature.
AP is step PR-AUC. The table uses a common **278-record budget** for all features;
recall counts all 23 positives, including unscored positives as missed.

| Feature | Known / unknown | Unknown positives | ROC-AUC | AP | TP / FP | Precision | Recall (all positives) |
|---|---:|---:|---:|---:|---:|---:|---:|
| amount | 20769 / 6989 | 9 | 0.547 | 0.002011 | 1 / 277 | 0.360% | 4.35% |
| velocity | 27758 / 0 | 0 | 0.689 | 0.001483 | 0 / 278 | 0.000% | 0.00% |
| median_ratio | 13416 / 14342 | 18 | 0.578 | 0.000605 | 0 / 278 | 0.000% | 0.00% |
| p95_ratio | 13416 / 14342 | 18 | 0.686 | 0.000792 | 0 / 278 | 0.000% | 0.00% |
| relative_velocity | 21130 / 6628 | 14 | 0.745 | 0.002056 | 2 / 276 | 0.719% | 8.70% |
| counterparty_novelty | 23235 / 4523 | 8 | 0.689 | 0.001107 | 0 / 278 | 0.000% | 0.00% |
| incoming_recency | 1185 / 26573 | 18 | 0.454 | 0.004609 | 1 / 277 | 0.360% | 4.35% |
| inflow_amount_match | 1117 / 26641 | 19 | 0.540 | 0.004726 | 0 / 278 | 0.000% | 0.00% |
| reciprocal_24h | 27305 / 453 | 0 | 0.541 | 0.002231 | 2 / 276 | 0.719% | 8.70% |
| fan_in_24h | 27305 / 453 | 0 | 0.588 | 0.002361 | 2 / 276 | 0.719% | 8.70% |

The original known-population 1% metrics and per-currency/payment-format
breakdowns are also retained in `results.json`; payment format is not a typology.
Common-known-cohort comparisons prevent confusing coverage changes with quality:
relative velocity versus raw velocity on 21,130 shared rows/9 positives has
AUC .745 versus .636 and AP .002056 versus .000805. This does not resolve the
14 excluded positives or establish an independent improvement. Matched-cohort
capacity is 1% of that shared cohort, not the full-population budget above.

## Uncertainty, ties and missing data

- Component-bootstrap precision-at-budget intervals include zero for every
  candidate. Relative-velocity AUC interval is [.674, .993], reciprocal [.498,
  .590], and fan-in [.478, .681]. Their all-positive recall intervals are
  [0, .267], [0, .185] and [0, .194]. These are descriptive intervals conditional
  on the incomplete observed graph, not proof of real-world generalization.
- Median/P95 uncertainty is NOT ESTIMABLE because their few known positives
  occur in too few observed components. Neither finds a positive at this budget.
- Relative velocity misses 14/23 positive labels because preceding-week count
  is zero. Its selected yield can range from 0 to 2 positives under different
  tie orders; raw velocity can range from 0 to 1. Source-row ordering is fixed,
  not an investigator preference or learned tiebreaker.
- Reciprocal and fan-in yield at least two positives regardless of cutoff tie
  ordering. Reciprocal has 119 positive-valued witnesses (2 generator-positive)
  and then fills the budget with tied zero-valued rows. Bounds including that
  tie group are 2–23; fan-in bounds are 2–5. These are combinatorial bounds,
  not confidence intervals. Do not treat a zero witness as absence of longer paths.
- Novelty has 9,816 tied novel observations, including 12 positives; a binary
  novelty flag alone cannot rank them usefully. Its tie-order TP range is 0–12.
- Incoming recency is known for only 1,185 targets and amount matching for 1,117;
  no prior inflow is unknown for these features, not imputed zero. Mixed-currency
  conversion is never invented. Self-transfers make flow/graph targets unknown.
- Median/P95 exclude 7,353 insufficient-history cases beyond the existing
  no-history and currency exclusions. All 90-day history is January-left-censored.
  Unknowns, reasons and positive coverage remain visible rather than dropped silently.

## Evidence and graph semantics

Each local feature record links the target source row, prior outgoing rows,
current 24h outgoing rows and strict prior 24h incoming rows, plus deterministic
counts/denominators. `evidence-check.json` independently reconstructs the two
generator-positive reciprocal witnesses from source rows and checks direction
and timing. Equal-minute incoming events are not ordered arbitrarily.

The sample preserves incident records for selected anchor accounts. Reciprocity
and fan-in are local observed patterns, not complete-graph cycle/chain results.
An amount match and short delay do not prove transfer of the same money, intent
or illicitness. Missing unsampled edges and customer ownership remain limitations.

## Runtime, verification and artifacts

Feature extraction: 5.624 seconds; peak process RSS 478.8 MiB.
Evaluation including 200-replicate bootstrap: 35.159 seconds; peak RSS 282.0 MiB.
These are offline batch measurements, not per-request runtime latency. The 28 MiB
feature/evidence cache remains ignored locally and can be reconstructed using
the recorded sample/protocol/code hashes. No large raw data or cache is committed.

19 targeted feature/baseline tests passed. One guarded integration checkpoint
passed **108 tests in 1.95 seconds**, covering native financial/graph/risk behavior
and the database guard. Repository-wide Ruff and mypy (108 source files) passed.
The later tie diagnostic passed two additional offline tests and scoped Ruff/mypy.
No full-suite rerun or demo-database mutation. No Docker/browser claim.

Commits: `b14cacf` defines features/protocol; `8f31835` records measurements and
tie diagnostics; final report committed separately. See `changed-files.txt`.

## Recommendations and approval requirements

1. Prioritize observed reciprocal-edge/fan-in witnesses for further temporal
   validation and potential evidence display, rather than an automatic risk score.
   Their 2/23 recall and 276 false positives at this budget remain weak evidence.
2. Keep relative velocity as a research candidate, requiring stronger history
   coverage and tie analysis. Do not silently impute zero-history accounts.
3. Do not adopt median/P95, binary novelty or inflow matching as ranking upgrades
   based on these results. Retain their negative findings without tuning directions.

January 17–23 on existing DEV components remains unmeasured and reserved for a
later locked temporal comparison. It shares accounts and is not independent
customer/graph validation. No old HELDOUT results were used to select candidates.
Next: lock a small candidate set and evaluation rules before using this reserve;
collect longer, compatible histories before production claims. Runtime adoption
requires a reviewed evidence contract and failure/unknown semantics; composite
scores or fitted thresholds remain gated by ADR-0005.

`independent-rag-review.md` supplies an independent-authoring workflow and
passage-support, abstention, applicability and citation rubrics for a new untouched
RAG set. No independent questions, labels or approvals were fabricated. Independent
RAG final validation remains pending. Current BGE-small and its existing gate
remain unchanged as instructed. LLM and UI stages were not started.

**STAGE 4 REVIEW READY — NO UNAPPROVED RUNTIME CHANGES**
