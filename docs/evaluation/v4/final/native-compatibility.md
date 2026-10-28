# Native compatibility and graph coverage assessment

Status: inspected current implementation; integration proposals only. No runtime
function, dispatch, evidence table, signal selection, schema or UI was changed.

## Actual contracts

- `agents/transaction/amount_deviation.py:compute_amount_deviation(engine, transaction_id)`
  resolves the source account to a customer and joins **all that customer's
  outgoing accounts** over [t-90 days,t). Currency mismatch/missing history is
  Unknown; computed output carries original transaction UUIDs. IBM experiments
  are one bank/account pair and do not validate this customer-level aggregation.
- `transaction_velocity.py:compute_transaction_velocity(engine, transaction_id)`
  uses the same customer mapping, inclusive [t-24h,t], and returns count plus
  ordered source UUIDs. Native input validation raises errors; there is no native
  Unknown result variant. IBM signed/missing-direction exclusions are additional
  source-adapter semantics, not proof of equivalent native behavior.
- `beneficiary_age.py:compute_beneficiary_age(engine, transaction_id)` looks up
  the customer/destination beneficiary records and earliest non-null added_at;
  absent destination/record/date or creation after target gives Unknown. IBM has
  no verified customer mapping or beneficiary creation date: external validation
  of this feature is BLOCKED BY DATA, not replaced by first observed transfer.
- `orchestration/transaction_agent_dispatch.py` executes all three computations.
  `graph_agent_dispatch.py` retrieves the requested context subgraph and calls
  cycle/chain computations with their own default four-hop bounds. The context
  max_hops argument is not forwarded as their detection depth; preserve that
  distinction instead of assuming identical bounds.
- `agents/report/authoring.py:build_authoring_drafts` creates deterministic
  evidence keys and separated fact/signal/interpretation drafts; authoring
  verifies nonempty, existing, correctly typed draft references. Persisted
  evidence/finding/recommendation IDs use UUID4, **not deterministic UUIDs**.
  The new offline artifact keys are deterministic UUID5 scoped by dataset,
  lock hash, account, row and signal, and are never presented as persisted IDs.
- `evidence/evidence.py:validate_evidence_reference` verifies allowed source
  tables, source existence and producer ownership by investigation. Findings
  validate evidence-run ownership; recommendations validate finding-run ownership.
  Report assembly revalidates references. Transaction source existence alone is
  not a universal customer-ownership check: new computations must constrain their
  source queries to the correct alert account/customer. Graph/counterparty
  evidence may legitimately span customers, so a blanket same-customer filter
  would be incorrect. Tests of run isolation do not prove every future source
  query safe.
- `investigation_orchestrator.py` gates COMPLETE on transaction and policy
  sufficiency, persists authoring/risk signals transactionally, and preserves
  fatal-agent failure handling. It already persists individual computed native
  signals; their status must not be confused with stale “unwired” module comments.
  Adding a candidate must not silently alter sufficiency or completion rules.

## Promising candidates: concrete integration work, not approval

| Candidate | Inputs/schema | Deterministic computation and unknowns | Evidence and performance | Migration/API/report implications |
|---|---|---|---|---|
| Account relative velocity | Alert transaction, source account, occurred_at, prior outgoing records; source/time index already exists | Inclusive current24h count / daily average in preceding nonoverlapping7d; require observable8d coverage; zero baseline and invalid direction Unknown. Decide account vs customer explicitly | Store target and both-window transaction UUIDs, counts and bounds; index range query, stable time/UUID ordering; EXPLAIN on representative data before deployment | No source-schema migration intrinsically required; add a result/Unknown type and versioned per-signal metadata/authoring only after approval. Do not reuse native velocity semantics/name |
| Observed reciprocal transfer | Source/destination account UUIDs, event time, directed transaction evidence; both source/time and destination/time indexes exist | Strict earlier reverse transfer within24h; exclude self-transfer. Unresolved endpoints/incomplete input coverage Unknown. False only means no observed witness in bounded local source | Retrieve reverse transaction UUIDs and exact timestamps, not an aggregate graph edge as proof of time ordering. Parameterized indexed query, deterministic witness ordering | No source migration for fully mapped transactions. New evidence type/authoring branch and explicit observation label required; API/report/UI must show window, coverage and IDs; no automatic case action |
| Observed fan-in | Destination account, prior incoming source accounts, timestamps, completeness | Count distinct verified sending account IDs in strict prior24h. Missing source identity is Unknown/partial, not one synthetic shared counterparty. Self-transfers excluded | Cite every contributing transaction and deterministic distinct identities; destination/time range scan. Bound evidence size with explicit truncation/Unknown semantics, never silently drop sources | No migration for mapped internal counterparties. External identity namespace may need schema/contract work if not reliably present; defer until required. Add separate fact/signal output, not risk band |

For each candidate, preserve optional additive API/report fields and existing
report output when disabled; add unit tests for boundaries, missing inputs,
identity isolation and FX, SQL/native parity tests, evidence producer/run tests,
authoring/report completeness tests and explicit opt-in dispatch tests before
activation. No new runtime tests are represented as implemented here.

Median/P95 would use existing amount/currency/time inputs but need the same
customer-vs-account decision and a sample-size/history contract. Novelty requires
stable counterparty identity and cannot be beneficiary age. Recency is possible
with mapped directed transactions but lacks strong measured ranking utility.
IBM paid-vs-received amount matching cannot be transferred faithfully to native
FX flows: `transactions` has a single amount/currency, not both paid and received
amount/currency pairs. A faithful FX adaptation could require a migration; there
is no evidence supporting that scope now. No automatic new schema is proposed.

## Graph completeness and event time

`subgraph.py` builds a NetworkX MultiDiGraph from all stored relationships.
Context reachability is undirected; simple paths respect direction. Limits are
500 nodes, 2,000 context edges and 100 returned paths. These caps constrain returned
exploration, **not the initial whole-table load**, which is a deployment scaling
limitation. `structure_signals.py` filters TRANSACTED_WITH, ignores self-loops,
chooses deterministic relationship witnesses and computes directed simple cycles
or chains through the selected account up to default four hops. A witnessed cycle
can be returned despite truncation; no-cycle under truncation is incomplete, and
truncated chain depth is a lower bound.

The graph schema has first_observed_at/last_observed_at, but current readers do
not apply an event-time cutoff and relationship rows do not encode the full
transaction sequence. Therefore a native current-snapshot path is not a faithful
as-of-transaction temporal witness. Do not import IBM ego edges and call a missing
path a negative or a native four-hop accuracy result.

| Capability | Assessment |
|---|---|
| Directed reciprocal transactions and local fan-in | Measured selected signals on complete delivered incident data for sampled anchors; unknown direction preserved |
| Observed fan-out | Supported as a descriptive distinct-recipient count from those anchors' outgoing records; no new ranker fitted or added |
| Short-window relationship ordering | Verified using strict event-time bounds; equal-minute ordering remains unresolved |
| Native bounded path/cycle computational correctness | Existing guarded synthetic fixture tests cover algorithm behavior, depth, truncation and deterministic ordering |
| Native graph detection accuracy against IBM labels | BLOCKED BY DATA: sampled missing edges, absent customer/entity mapping and no scenario/path ground truth; current graph reader also lacks as-of filtering |
| Real-world graph/AML effectiveness | UNKNOWN |

Layering example: **fact** A received from B before sending to B, citing both
transactions; **signal** prior-24h reciprocal witness=1; **interpretation** a local
return-transfer pattern with unknown purpose; **recommendation** investigator may
review cited records/context. No laundering conclusion, fund identity assertion
or irreversible action follows. Non-observation is not global graph absence.

No independent runtime correctness fix was necessary for this evaluation.
As-of graph reads, global graph-load cost, context-vs-detection bounds and source
eligibility are explicit integration constraints requiring focused follow-up,
not silently changed runtime contracts.
