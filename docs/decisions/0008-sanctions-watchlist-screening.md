# ADR-0008: Sanctions/Watchlist Screening Approach (F11)

Status: Accepted
Date: 2026-10-08

## Context

- FACT: F11 (`docs/FEATURES.md`) and `docs/ARCHITECTURE.md` §4.7 describe sanctions/watchlist screening as a Phase 2 agent that is not yet designed. `docs/ROADMAP.md` requires each new agent to be documented per `docs/ARCHITECTURE.md` §4 before merge.
- FACT (HEAD `fdf6e9b`): no sanctions or watchlist code, table, migration, dispatch, screening-result persistence or test exists.
- FACT: `customers.full_name` and `customers.date_of_birth` are nullable. `alerts.customer_id` identifies the customer for every alert. `beneficiaries` has no name column. `transactions` has only `counterparty_external_ref`. The F11 text "customer/counterparty names" is therefore not supportable by the current schema.
- FACT: `entity_resolution/matching.py` provides `normalize_full_name()` (NFKC, casefold, whitespace collapse) and `NORMALIZATION_VERSION = "v1"`, with tests for case, whitespace (including NBSP and ideographic space), NFKC, empty and blank inputs.
- FACT: `record_agent_run()` (`src/meridian/orchestration/agent_run_tracking.py`) opens and commits its own transaction, cannot join the caller's transaction, and writes only `SUCCESS` or `FAILED`. Investigation authoring runs in the orchestrator's own transaction (`orchestrate_investigation` → `author_investigation_records(conn, outcome)` plus risk-signal persistence). A rollback of authoring does not roll back an agent run.
- FACT: `get_case_audit_trail()` explicitly reads `cases`, `investigation_runs`, `agent_runs`, `evidence`, `findings` and `audit_events`. It does not know about any F11 table.
- FACT: the `agent_runs` schema has no outcome or result column. `evidence` is a reference to a real row, not a payload. `findings` hold prose. None of them can carry an F11 domain outcome without inference or parsing.
- FACT: ADR-0005 forbids presenting scores or thresholds fitted to generator-defined data. ADR-0006 defers persistence and wiring of entity-resolution links and defines identity-candidate semantics that differ from screening semantics. ADR-0007 (Proposed) covers authentication and is not changed by this ADR.
- Consequence: F11 needs (a) a structured, resolvable watchlist, (b) one authoritative record of the screening outcome that does not depend on absence or presence of other rows, and (c) a persistence model that is honest about the two independent commits that exist today.

## Decision (Accepted 2026-10-09)

### D1. Scope

F11 screens exactly one entity type: the customer identified by `alerts.customer_id`, using `customers.full_name` and `customers.date_of_birth`, against a synthetic watchlist.

Not screened: beneficiaries, counterparties, accounts, devices, merchants, or any entity the current schema cannot name. No external, public or live list is used. F11 documentation must drop "counterparty names" until a schema change makes counterparty names available, which would require its own decision.

### D2. Candidate semantics

F11 is a candidate-generation mechanism. The semantic chain is:

normalized-name equality → candidate → DOB comparison → human review.

It is never: name + DOB → identity confirmed → sanctions determination.

A candidate does not establish identity, sanctions status, criminality, or any AML conclusion. All Meridian-authored wording must say so.

### D3. Matching rule

- Rule identifier: `exact_norm_name_v1`.
- A candidate exists when the normalized customer name equals the normalized listed name of any entry (primary or alias) of a watchlist subject.
- One candidate per `subject_key`, listing every matched entry. Two subjects sharing a normalized name yield two candidates; they are never merged.
- DOB is a candidate attribute, not a gate. `dob_comparison` is `EQUAL`, `DIFFERENT` or `NOT_COMPARABLE` (either side null). It does not rank candidates, alter confidence, or suppress a candidate.
- Excluded: fuzzy, phonetic, transliteration, token-reorder, nickname, typo-tolerant, embedding, ML and LLM matching. No thresholds exist. Exact matching is trivially evaded by any variant; this ADR makes no real-world screening claim.

### D4. Normalization reuse and versioning

- F11 imports `normalize_full_name()` and `NORMALIZATION_VERSION` from `entity_resolution.matching`. The normalizer is not duplicated.
- F11 declares `EXPECTED_NORMALIZATION_VERSION = "v1"` and verifies it equals the imported value. A mismatch is a technical integrity failure (D8), never a silent behavior change.
- Tests must pin representative normalization behavior (casefold, whitespace runs, NBSP-only input, a fullwidth NFKC case), not only the version string, so a behavior change cannot masquerade as the same F11 rule version.
- F11 imports only the normalizer. It does not consume or produce ER links, so the ADR-0006 D5 prohibitions are not triggered. Dependency direction is `agents.sanctions` → `entity_resolution`. A test must guard that `entity_resolution` never imports `agents.sanctions`. Extracting a neutral shared normalizer module is a possible later refactor and is not part of F11.

### D5. Watchlist schema, loading and immutability

New table `watchlist_entries`, one row per listed name:

- `entry_id` UUID PK (deterministic `uuid5`)
- `watchlist_name` text NOT NULL, `watchlist_version` text NOT NULL
- `subject_key` text NOT NULL (groups a primary name and its aliases)
- `name_type` text NOT NULL, CHECK in (`primary`, `alias`)
- `listed_name` text NOT NULL, CHECK non-blank
- `date_of_birth` date NULL
- `is_synthetic` boolean NOT NULL, CHECK = true
- `source` text NOT NULL, `created_at` timestamptz NOT NULL
- UNIQUE (`watchlist_name`, `watchlist_version`, `subject_key`, `name_type`, `listed_name`); index on (`watchlist_name`, `watchlist_version`)

Rules:

- The privileged loader validates the whole version before inserting anything and loads it in one transaction. An invalid version commits nothing and never becomes pinnable. Validation requires: every `listed_name` non-empty after normalization; valid `name_type`; exactly one `primary` entry per `subject_key`; identical `date_of_birth` (including null) across all rows of a `subject_key`; `is_synthetic` true.
- Versions are immutable. The loader refuses to add rows to an existing `(watchlist_name, watchlist_version)`. New content means a new version. Rows are never deleted, because evidence references them.
- The application role has SELECT only on `watchlist_entries`.
- No stored normalized name (computed in memory), no active flag, no effective dates, and no `watchlist_versions` table. Consequence: a version's content hash is verified by tests against a frozen manifest, not at runtime.
- Runtime re-validation of loaded rows is retained only as defense in depth. Any runtime validation failure is a technical integrity failure (D8), not an abstention, because it means the loader guarantee was violated.

### D6. Watchlist pin and provenance

- The screened `(watchlist_name, watchlist_version)` is a code constant owned by the F11 module. The dispatch layer passes it to the agent as an explicit parameter. It changes only through a reviewed commit.
- Queries filter by exact name and version with bound parameters. `MAX(version)`, `ORDER BY version`, "latest" lookups and environment-variable pins are prohibited, and a test must guard against them.
- Every `screening_results` row records the pin, including abstentions. Candidate evidence references `watchlist_entries` rows, which carry name, version and `source`.

### D7. Authoritative screening outcome: `screening_results`

New table `screening_results`, one row per investigation run:

- `screening_result_id` UUID PK
- `investigation_run_id` UUID NOT NULL FK, UNIQUE
- `agent_run_id` UUID NOT NULL FK, UNIQUE
- `customer_id` UUID NOT NULL FK
- `outcome` text NOT NULL, CHECK in (`CANDIDATE_MATCHES_FOUND`, `NO_CANDIDATE_MATCH`, `NOT_PERFORMED`)
- `reason_code` text NULL
- `candidate_count` integer NOT NULL, CHECK >= 0
- `watchlist_name`, `watchlist_version`, `matching_rule_id`, `normalization_version` text NOT NULL
- `created_at` timestamptz NOT NULL
- CHECKs: `reason_code` is NOT NULL if and only if `outcome = NOT_PERFORMED`, and then must be in the D8 abstention set; `candidate_count > 0` if and only if `outcome = CANDIDATE_MATCHES_FOUND`.
- Application role: SELECT and INSERT only (append-only, same grant pattern as `agent_runs`).

Critical invariants:

> F11 screening state is determined from the persisted `screening_results` outcome when a result exists. It MUST NOT be inferred from `agent_runs`, candidate evidence presence or absence, findings text, or report text.

> `agent_runs.status` describes agent execution status. `screening_results.outcome` describes the F11 domain outcome.

ERROR is not a stored screening outcome. A technical failure may be a database failure, so a result row cannot be guaranteed. A technical error is represented by `agent_runs.status = FAILED` with a reason code in `error`, and by the absence of a `screening_results` row.

Consistency checks may compare evidence or findings against a result row (for example, `candidate_count` against the number of candidate findings) to detect defects. They never derive the outcome.

### D8. Agent-run semantics and failure model

| F11 situation | `agent_runs.status` | `screening_results` | Reason |
|---|---|---|---|
| Candidate match found | SUCCESS | `CANDIDATE_MATCHES_FOUND` | none |
| Screening completed, no candidate | SUCCESS | `NO_CANDIDATE_MATCH` | none |
| Controlled abstention | SUCCESS | `NOT_PERFORMED` | `reason_code` |
| Technical or integrity failure | FAILED | no row | code in `agent_runs.error` |

Controlled abstention is a successful execution that correctly determined it cannot screen. Abstention reason codes (stored in `reason_code`):

- `CUSTOMER_NAME_MISSING` (null name)
- `CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION`
- `WATCHLIST_VERSION_NOT_LOADED` (the pinned `(name, version)` has zero rows)

A null customer DOB is not an abstention; screening proceeds with `dob_comparison = NOT_COMPARABLE`.

Technical failure codes (written to `agent_runs.error`, never to `screening_results`):

- `WATCHLIST_INTEGRITY_VIOLATION` (a runtime-loaded row fails D5 validation)
- `NORMALIZATION_VERSION_MISMATCH`
- `DATABASE_ERROR`
- `UNEXPECTED_ERROR`

Error text carries a reason code only, never customer or watchlist names. `record_agent_run()` and the generic agent-run state machine are not changed, and `PARTIAL` is not used. `agent_runs.status = SUCCESS` alone does not mean "screened"; only `screening_results` does.

### D9. Persistence model, consistency and investigation status

Persistence is two-stage and is deliberately not claimed to be atomic.

Stage 1: the F11 dispatch wraps the read-only screening function in `record_agent_run()`, which commits the `agent_runs` row (SUCCESS or FAILED) in its own transaction.
Stage 2: the orchestrator's authoring transaction writes `screening_results`, candidate evidence, findings and recommendations together, referencing the Stage 1 `agent_run_id`. Evidence rows set `produced_by_agent_run_id` to that id.

Required behavior:

1. A `screening_results` row is written only when a persisted SUCCESS `SanctionsAgent` run for the same `investigation_run_id` exists. Authoring verifies this in-transaction. It does not write F11 records for a FAILED run or without an `agent_run_id`.
2. Agent run SUCCESS but authoring fails and rolls back: a SUCCESS run exists with no result row. This is an inconsistent state, rendered as such (D10), never as no-match.
3. Stage 1 agent-run persistence fails: no `agent_run_id` exists, so F11 authoring does not occur. The failure must be explicitly handled and disclosed as not determined; it must not be silently swallowed.
4. Retries and duplicates: the two UNIQUE constraints make a second result for one run, or reuse of one agent run, impossible at the database level. A unique violation is an integrity defect, not silently ignored. Only the `agent_run_id` of the attempt that produced the authored outcome is referenced.
5. Authoring verifies that the referenced agent run has `agent_name = 'SanctionsAgent'` and the same `investigation_run_id`. This is an application check, because no composite FK exists and `agent_runs` is not changed.
6. `get_case_audit_trail()` must be extended to include `screening_results` when F11 is wired. Until then F11 outcomes are not reconstructable from the audit trail, and this must be stated wherever F11 is described as wired.

Investigation status: F11 abstention and failure do not change the existing investigation completion rule (`COMPLETE` depends on the existing transaction and policy evidence). F11 failure is non-fatal to the investigation, unlike a transaction or policy agent failure. This is not an implicit clearance: disclosure of `NOT_PERFORMED`, technical error and inconsistent states in the report is mandatory.

Proposed F11-specific exception: F11 screening failure or controlled abstention does not change the existing investigation completion state. This requires explicit reconciliation of `docs/AI_SAFETY_AND_GUARDRAILS.md` §6 before F11 wiring. Until that reconciliation is completed, F11 must not be implemented. This ADR does not itself amend or reinterpret the AI safety document, and that document is not modified by this ADR.

### D10. Evidence, finding and report chain

Evidence (new constants in `evidence/evidence.py`): a `screened_customer` row referencing `customers`, and one `watchlist_entry` row per matched entry referencing `watchlist_entries`.

Per candidate subject, one `INVESTIGATIVE` finding and one fixed-template human-review recommendation (existing one-recommendation-per-finding rule). Confidence stays at the existing `LOW` floor, which is not a probability or risk level. No `risk_signals` row and no composite score (ADR-0005).

- Observed Fact: the customer's normalized name equals a listed name on synthetic list `<name>` `<version>` under rule `exact_norm_name_v1`, normalization `v1`.
- Derived Signal: exact normalized-name equality; `dob_comparison = EQUAL | DIFFERENT | NOT_COMPARABLE`.
- Interpretation: "Candidate watchlist match for human review. Not an identity or sanctions determination. Synthetic list. No validated threshold."
- Recommendation: the existing fixed human-review template.

Authoring changes (including the existing rule that reference findings cite only policy evidence) are scoped to the wiring task.

The report always contains a watchlist screening section, rendered from persisted state as follows. A result row governs; a consistency check failure overrides to INCONSISTENT.

| Persisted state | Rendered as |
|---|---|
| Row `CANDIDATE_MATCHES_FOUND`, consistent | Candidates, with list name, version and rule |
| Row `NO_CANDIDATE_MATCH` | "No candidate match against synthetic list X vN. This is not a clearance." |
| Row `NOT_PERFORMED` | "Not determined", with the reason |
| No row; a `SanctionsAgent` run for the same `investigation_run_id` with status FAILED | "Screening error. Not determined." |
| No row; a `SanctionsAgent` run for the same `investigation_run_id` with status SUCCESS (or PARTIAL) | "Inconsistent screening record. Not determined." |
| No row; no `SanctionsAgent` run for the same `investigation_run_id` | "Screening not recorded. Not determined." |
| Row exists but the referenced run is not a SUCCESS `SanctionsAgent` run of the same investigation run, or `candidate_count` does not equal the candidate finding count | "Inconsistent screening record. Not determined." |

Wording prohibited in Meridian-authored text: "sanctioned customer", "confirmed hit", "criminal", "money laundering", "cleared", "clean", "no sanctions exposure". Candidate wording must state it is a candidate for human review and not an identity or sanctions determination. Logs carry reason codes and counts only, never names. This table also provides the "Not determined" rendering for F11 only; the general F7-B deferral is unchanged.

### D11. Evaluation boundary

Only deterministic fidelity of the matcher against a frozen synthetic corpus is measurable: confusion counts per (customer, subject) pair, stratified by variant class, with abstention accounting by reason code, tier PROTOTYPE, naming the corpus and watchlist versions. The protocol is frozen before measurement, in the style of `docs/EVALUATION.md` §5. Expected misses (typo, token reorder, nickname, diacritic, transliteration) are reported honestly as out-of-scope false negatives, not defects.

Not claimable: screening effectiveness, real-world recall or precision, ROC-AUC, thresholds, calibration, regulatory screening compliance.

### D12. Non-goals

No external, public or live lists. No counterparty, beneficiary, account, device or merchant screening. No fuzzy, phonetic, ML, embedding or LLM matching. No risk score or risk level. No new role or access path (ADR-0007 unaffected). No ER links consumed or produced. No account action, freeze or closure. No regulatory filing. No sanctions, suspicious-activity or identity determination. No new database, service, queue or framework. No change to ADR-0005, ADR-0006, `record_agent_run()` semantics or the global investigation state machine.

## Alternatives Considered

- **DOB-gated matching (ER semantics):** rejected. It discards candidates when DOB is missing or wrong, which is the costlier error in screening. ER makes an identity claim, and F11 does not.
- **Fuzzy or phonetic matching now:** rejected. It needs thresholds and independent calibration data (ADR-0005 spirit).
- **Watchlist stored in `customers` or as document chunks:** rejected. It would pollute the ER universe, or put structured data into unstructured RAG storage.
- **Infer screening state from `agent_runs` plus evidence presence:** rejected. Absence cannot distinguish match, no-match, abstention and error.
- **Store the outcome in `agent_runs.tool_calls`, `error`, or findings text:** rejected. It violates the static-summary convention, abuses the failure field, or requires parsing prose.
- **Atomic agent run, result and evidence:** rejected. It is not achievable without changing `record_agent_run()`, and inventing a transaction abstraction to look atomic is out of scope.
- **Map abstention to FAILED or add a PARTIAL state:** rejected. A controlled abstention is not a technical failure, and a new state would change shared agent-run code.
- **INCOMPLETE_INSUFFICIENT_EVIDENCE on abstention:** rejected. It would mark every investigation on a database without the pinned list as incomplete, and it conflates screening with the primary evidence rule.
- **Runtime fail-closed on one bad entry as the primary control:** rejected in favor of whole-version load validation; runtime validation is defense in depth only.
- **Environment-variable or "latest" pin; `watchlist_versions` table:** rejected as silent drift, or as unneeded machinery.
- **Duplicating the normalizer, or extracting a shared module now:** rejected for this slice.

## Consequences

- Two new tables: `watchlist_entries` (Task 23) and `screening_results` (wiring task). Schema documentation is updated when each is implemented.
- `agent_runs.status = SUCCESS` for `SanctionsAgent` does not by itself mean "screened". Report and audit consumers must read `screening_results`.
- Inconsistent and not-recorded states are possible by design of the two-stage commit, and are detected and disclosed, not prevented.
- A watchlist version's content hash is not verifiable at runtime. Frozen-manifest tests are the control.
- Exact matching is trivially evaded; the synthetic evaluation says nothing about real screening.
- F11 failure is non-fatal to the investigation, and disclosure replaces fatality. This is a proposed F11-specific exception that requires reconciliation of `docs/AI_SAFETY_AND_GUARDRAILS.md` §6 before F11 wiring; F11 must not be implemented until that reconciliation is complete.
- A real or public list, fuzzy matching, or counterparty screening each requires a new ADR, and EXTERNAL license verification for any real list.

## Implementation sequencing (non-binding)

- Task 23: `watchlist_entries` migration and grants, validating loader, deterministic synthetic watchlist corpus with frozen manifest, pure matcher and outcome types, tests, and the PROTOTYPE fixture-fidelity baseline. No wiring.
- Task 24: `screening_results` migration, `SanctionsAgent` dispatch with static `tool_calls`, pin constant, orchestrator wiring, authoring, report section, audit-trail extension, safety tests, and documentation reconciliation. Verify the `record_agent_run()` failure and exception behavior first.

## Scope of this ADR

This ADR authorizes no code, migrations, tables, fixtures, tests, UI, dispatch, or any write to existing tables. Each implementation task requires its own approved prompt.
