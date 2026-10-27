# Stage 4 deterministic financial DEV protocol — v1

Status: definitions fixed before candidate performance measurement. Offline
account-unit research only; no runtime, ADR, threshold or composite-score change.
Dataset and label semantics remain those in v2: IBM 2021 synthetic illicit-origin
funds labels, not AML determinations. Reuse the unchanged 789,860-row sample with
SHA256 f83babca4a2c3d99f6e0f411819b78eed6f59557a3e25c426ed3bc2a890860a8.
No archive download or full-source scan. Prior frozen results remain immutable.

Keep v2 observed-component assignment and DEV targets January 10 inclusive to
January 17 exclusive. No HELDOUT scores or labels enter selection. Reserve January
17 inclusive to January 24 exclusive on DEV components without computing outcomes.
This is a possible temporal test, not independent accounts or a new dataset; it
requires a locked selection before future measurement. Existing HELDOUT remains
inspected evidence and is not a fresh test. Hidden ownership/omitted edges mean
full-source graph independence remains unproven.

## Features (higher scores first, no fitted directions)

- Baselines: unchanged v2 account mean-amount ratio and inclusive 24h count.
- Median amount ratio: target paid / median strictly earlier 90-day outgoing
  amounts. At least five historical records; same missing, signed and mixed-
  currency exclusions as baseline. Median averages the middle pair.
- P95 amount ratio: target paid / nearest-rank 95th percentile of the same
  history; at least five records. No claim that five observations estimate a
  reliable tail quantile. Zero denominators are unknown.
- Relative velocity: inclusive current 24h outgoing count / average daily count
  in preceding seven days [t-8d,t-1d). Requires eight days since dataset start.
  No overlap between windows; zero baseline/missing/signed directions unknown.
- Counterparty novelty: 1 if target receiving bank/account is absent from strict
  prior 90-day outgoing history, otherwise 0. No prior history or signed/missing
  paid direction is unknown. No inferred beneficiary creation date or ownership.
- Incoming recency: 1/(1+minutes since most recent strictly prior incoming event
  in 24h). No earlier incoming event is unknown, not a zero lag. Target and incoming
  directions must have nonnegative, present amounts. Equal timestamps cannot
  establish an ordering and are excluded from incoming witnesses.
- Amount match to recent inflow: min(target paid, prior 24h received sum) divided
  by max of the two, same-currency only; zero/no inflow or unknown amount/currency
  is unknown. This measures amount similarity, NOT tracing the same money or
  proving pass-through. Known different currencies are not converted.
- Observed reciprocal edge in prior 24h: 1 if an earlier incoming sender equals
  target receiver, otherwise 0. This is a local timed witness on a sampled anchor,
  not a complete-graph cycle/chain result. Unsupported direction makes it unknown.
- Observed fan-in: distinct prior 24h incoming bank/account senders, excluding the
  anchor itself. Zero means no observed distinct incoming sender in this local
  window, never proof that no paths exist in the incomplete graph.

Target self-transfers make flow/graph features unknown; self-transfers are
also excluded from incoming flow/graph witnesses because they do
not establish movement between distinct accounts. Source minute-resolution ties
are grouped. Feature calculations use only events at/before target; strict
historical and incoming quantities exclude all tied events. Original duplicate
records are retained. All windows are left-censored by January source coverage;
there are no invented pre-January records, FX rates, KYC or typology IDs.

## Metrics, comparability and evidence

Reuse v2 ROC-AUC (half-credit ties), step average precision, known-population
1% capacity, unknown counts/reasons and per-currency/format reporting. Additionally
report a common fixed budget ceil(0.01 * ALL DEV targets) for every candidate,
with TP/FP, precision and recall against ALL positive targets (unknowns count as
unreviewed). Also report paired common-known-cohort baseline comparisons so
coverage differences are visible. Never interpret payment format as a typology.
200 component-bootstrap replicates, seed 20261027, give descriptive AUC/AP and
fixed-capacity precision/recall intervals when at least two positive components
exist. These reflect incomplete observed components, not real-world independence.
Ties use original source-row order; binary features can yield arbitrary capacity
selection within a large tied group, which must be disclosed.

Cache per-target features and contributing row IDs locally, keyed by sample,
protocol and code hashes. Each feature remains a separate derived value; do not
combine or select weights. Measure extraction, evaluation latency and peak RSS.
Prefer candidates with useful fixed-budget recall/precision and acceptable
missingness, but report inconclusive effects with only 23 prior DEV positives.
No runtime adoption or claims of calibrated detection utility are authorized.
