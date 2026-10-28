# Stage 4 final decision

Status: **COMPLETE — research and engineering assessment**, with external native
customer/graph accuracy BLOCKED BY DATA and independent validation pending.
Retain current runtime signals and BGE-small. No candidate is approved for runtime
adoption; no composite score, fitted production threshold or AML determination.

## All candidates accounted for

TP counts below use an absolute 278-review budget, source-row ascending tie order.
DEV: 27,758 targets/23 positives. Reserve: 33,113 targets/29 positives.
Coverage is known targets / known positive labels; it is not accuracy.
Unselected candidates retain their original DEV measurements, without reserve reruns.

| Signal | DEV TP; known/positive coverage | Reserve TP; known/positive coverage | Decision |
|---|---|---|---|
| Existing amount ratio | 1; 20,769/14 | 0; 25,222/11 | RETAIN existing behavior; weak synthetic ranking |
| Existing velocity | 0; 27,758/23 | 0; 33,113/29 | RETAIN existing behavior; no demonstrated replacement |
| Historical median ratio | 0; 13,416/5 | Not selected | REJECT current ranking adoption |
| Historical P95 ratio | 0; 13,416/5 | Not selected | REJECT current ranking adoption |
| Relative velocity | 2; 21,130/9 | 0; 21,932/12 | REJECT current ranking adoption; longer-history research only |
| Counterparty novelty | 0; 23,235/15 | Not selected | REJECT standalone ranking adoption |
| Incoming-transfer recency | 1; 1,185/5 | Not selected | RESEARCH ONLY as observed context |
| Incoming/outgoing amount match | 0; 1,117/4 | Not selected | REJECT current ranking adoption |
| Reciprocal-transfer witness | 2; 27,305/23 | 2; 32,477/29 | RESEARCH ONLY; strongest repeatable observed fact |
| Observed fan-in | 2; 27,305/23 | 1; 32,477/29 | RESEARCH ONLY as observed context |

These are decisions about present adoption, not claims a feature can never help.
Computational parity and boundary tests support implementation correctness; they
cannot establish predictive usefulness. Existing runtime retention preserves
contracts rather than claiming its rankers outperform all candidates.

## Locked temporal measurement

The lock was committed in `23c3061` before extraction/measurement. Only the five
selected formulas were evaluated once on [2019-01-17,2019-01-24), using the existing
DEV component assignment. No formulas, selection, thresholds or ranking rules
were refitted afterward. This shares accounts/components with DEV and is **not
independent customer-level validation**. Existing HELDOUT was not used.

| Signal | ROC-AUC | PR-AUC (step AP) | TP / FP / FN, all positives | Precision / recall @278 | Unknown targets / positives |
|---|---:|---:|---|---|---|
| Amount | .20761 | .000277 | 0 / 278 / 29 | 0% / 0% | 7,891 / 18 |
| Velocity | .71186 | .001615 | 0 / 278 / 29 | 0% / 0% | 0 / 0 |
| Relative velocity | .69367 | .003004 | 0 / 278 / 29 | 0% / 0% | 11,181 / 17 |
| Reciprocal | .53302 | .002253 | 2 / 276 / 27 | .7194% / 6.8966% | 636 / 0 |
| Fan-in | .61340 | .001640 | 1 / 277 / 28 | .3597% / 3.4483% | 636 / 0 |

AUC/AP use known scores only; recall/FN above include unknown positives. Do not
compare AP across different coverage as if populations were identical. JSON also
retains legacy 1%-of-known capacity fields; the `fixed_budget` fields are the
primary comparisons here. All measured metrics, matched cohorts, intervals and
valid bootstrap counts are in `results.json`.

200 component-bootstrap replicates, seed 20261027, give conditional 95% percentile
intervals. Reciprocal ROC [.4984,.5892], AP [.000679,.009113], precision
[0,1.7986%], recall [0,18.1818%]; fan-in ROC [.5118,.6875], AP
[.000678,.003313], precision [0,1.0791%], recall [0,8.5714%]. Relative
ROC [.4900,.9699], AP [.000948,.009646] (199 defined AUC/AP replicates).
Zero-TP bootstrap intervals for the other capacity metrics reflect this sample,
not proof of zero population performance. Only 25 positive-bearing observed
components support graph intervals, eight relative-velocity components and 11
amount components. These are not real-world confidence guarantees.

Common-known comparisons preserve budget278: reciprocal vs amount has 24,929
rows/11 positives and TP1 vs0; vs velocity has 32,477/29 and TP2 vs0. Fan-in
has TP0 vs0 and TP1 vs0 on those respective cohorts. Relative vs amount has
18,615 rows/5 positives and AUC .973 vs .242 but TP0 vs0; vs velocity has
21,932/12 and AUC .694 vs .709 with TP0 vs0. High AUC in a tiny selected
positive cohort is not evidence of a useful operational improvement.

Tie sensitivity is material: reciprocal has 97 score-one observations (2
positives), then 32,380 zero-score ties; arbitrary tie orders could produce
TP2–29 at capacity. Fan-in TP0–1; relative, amount and velocity TP0–0.
These are possible-order bounds, not confidence intervals. Original DEV bounds
were reciprocal2–23, fan-in2–5 and relative0–2. Temporal evidence therefore
supports a repeated reciprocal observation, not a reliable automated ranker.

## Definitions, missingness and provenance

`../PROTOCOL.md` and frozen `intelligence.py` define all eight formulas and exact
IBM fields; `reserve-lock.json` binds code, sample, direction, ties and metrics.
Median/P95 use strictly prior90d paid amounts, minimum5 observations; P95 is
nearest-rank, median averages a middle pair. Relative velocity divides inclusive
24h outgoing count by the preceding nonoverlapping7d daily mean. Novelty checks
prior90d recipient pairs. Recency uses 1/(1+minutes since last strictly prior24h
incoming); amount match uses min/max of target paid and prior24h received sum in
the same currency. Reciprocal checks strictly prior24h reverse transfers; fan-in
counts distinct prior24h senders. Higher scores rank first; original row IDs break
ties. No currency conversion is performed. No observed incoming/history may be
Unknown rather than zero; self-transfer and invalid-direction exclusions remain.

Insufficient history dominates median/P95 (only five known positives), relative
velocity (14 DEV and17 reserve positives unknown), and incoming features (only
five/four known DEV positives). Novelty has 9,816 equal novel scores, including12
positives: its arbitrary row-order ranking obscures usefulness. Reserve amount
has3,973 no-history and3,918 mixed-currency unknowns. Graph636 unknowns are target
self-transfers. Class imbalance, incomplete observed graphs and left-censoring
prevent strong conclusions; zero observed witness is not global graph absence.

All33,113 reserve targets were audited against56,235 resolved original source
rows, with165,565 unique deterministic scoped offline evidence keys. Strict
incoming/prior-week and inclusive outgoing boundaries, account identity, graph
values and amount-history reconstruction bounds passed. See `source-audit.json`
and its exact executed script. Amount-history bounds are checked, not an
independent full recalculation of every historical mean. Source business-duplicate
records are preserved with distinct row IDs; equal-minute incoming records are
excluded because their order is unknown. Same-minute outgoing velocity remains
inclusive by the existing contract, so event-time availability requires the full
minute bucket and is not a claim of instantaneous streaming availability.

## Graph and native integration

Directed reciprocal transfers and local fan-in are supported observed facts.
Descriptive inclusive24h fan-out spans1–16 counterparties (mean1.30855); no ninth
ranker was added. Native depth/cycle accuracy against IBM is BLOCKED BY DATA:
no verified customer ownership, incomplete sampled paths, no path-level truth,
and native current-snapshot graph reads lack an as-of filter. Synthetic native
algorithm regression tests verify bounded traversal, not external AML accuracy.

`native-compatibility.md` records source/schema, evidence, Unknown handling,
time/query/index costs, migration decisions, API/report effects and required
activation tests. Local transaction witnesses could support optional future
investigator facts with approval. Account experiments do not validate native
customer aggregation; beneficiary age cannot be tested with these source fields.
FX amount matching lacks a faithful native paid/received dual-amount mapping.
Graph whole-table loading and context/detection depth differences remain explicit
integration constraints. No schema, runtime dispatch or report selection changed.

## Verification and reproducibility

Final guarded integration: **199 passed**, one existing Starlette/httpx deprecation
warning,7.95s. Ruff passed; mypy passed110 source files. The checkpoint covers
feature parity, duplicate/timestamp boundaries, scope isolation, stable keys,
lock rejection, native transaction/graph behavior, evidence integrity, report
assembly and orchestration. Full suite, Docker rebuild and browser smoke were
not repeated. Source audit PASS is separate from these tests.

Extraction6.880s, process peak RSS608,387,072bytes; measurement28.229s,
peak288,210,944bytes. These are local batch costs, not per-request runtime latency.
`REPRODUCE.md`, receipts and hashes preserve exact inputs/configuration. Old
Stage1–3 and Stage4 DEV evidence remains unchanged; no raw sample/cache is committed.

IBM synthetic generator labels are not regulatory determinations. DEV has only23
positives; reserve29. Financial history is left-censored, sampled graphs are
incomplete, beneficiary metadata/customer ownership absent, reserve nonindependent.
Real-world AML accuracy remains UNKNOWN. Independent RAG labels/review remain
pending; the existing untouched-set human-review package is preserved.

Stage5 is proposal only in `stage5-proposal.md`: requires explicit bounded scope,
provider/privacy/budget decisions and safety acceptance before implementation or
paid use. No approval is requested for further Stage4 runtime adoption because
current evidence does not justify it.
