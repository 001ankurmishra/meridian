# Feature Specification — Project Meridian

**Read every coding session?** Yes, for the feature area being touched.

Each feature below states its phase (per `docs/ROADMAP.md`), the module(s) that own it (`docs/ARCHITECTURE.md` §3), and its Definition of Done reference (`docs/DEVELOPMENT_RULES.md` §6).

---

## F1. Alert Intake

**Phase:** MVP · **Module:** `case_management`

Ingests an AML alert (from the synthetic monitoring generator, `docs/DATA_AND_DATASET_STRATEGY.md`) and creates a `cases`/`alerts` record. Validates required fields (customer, triggering transaction or pattern, alert reasons). Rejects malformed alerts with a clear error rather than creating a partial case.

## F2. Investigation Orchestration

**Phase:** MVP · **Module:** `orchestration`

Runs the rule-based dispatch described in `docs/ARCHITECTURE.md` §5: creates an `investigation_run`, dispatches TransactionAgent and PolicyAgent (and GraphAgent when triggered), gates report generation on evidence sufficiency, and marks `investigation_runs.status` accurately (`COMPLETE` / `INCOMPLETE_INSUFFICIENT_EVIDENCE` / `FAILED`).

## F3. Transaction Anomaly Analysis

**Phase:** MVP · **Module:** `agents.transaction`

Computes, via SQL against `transactions`/`accounts`, the alerted transaction's deviation from the customer's historical behavior (e.g., multiple of trailing average, velocity of recent transactions, presence of a newly created beneficiary). Every computed signal links to the specific source rows used.

## F4. Basic Transaction Graph

**Phase:** MVP · **Module:** `agents.graph`

Builds a bounded-depth subgraph around the alerted customer/account from `graph_relationships`/`transactions`, runs basic NetworkX analysis (e.g., path detection for rapid pass-through patterns like the worked example: Customer A → Account B → Account C). Phase 2 adds community detection and centrality scoring (`docs/ROADMAP.md`).

## F5. Policy Retrieval (RAG)

**Phase:** MVP · **Module:** `agents.policy`, `retrieval`

Given the alert pattern, retrieves relevant policy/regulatory chunks via hybrid (BM25 + vector) search over `document_chunks`. Returns citations with document ID + version. Applies a minimum relevance-confidence threshold (`docs/EVALUATION.md`); below threshold, returns no citation rather than a weak one.

## F6. Evidence Collection & Linking

**Phase:** MVP · **Module:** `evidence`

Every finding produced by any agent must be backed by one or more `evidence` records pointing to concrete source data (transaction, beneficiary, graph relationship, policy chunk, or risk signal). Enforced at the data-model level (`findings.evidence_ids` non-empty) and the application level (`docs/AI_SAFETY_AND_GUARDRAILS.md`).

## F7. Investigation Report Generation

**Phase:** MVP · **Module:** `agents.report`

Synthesizes `findings`/`evidence`/`recommendations` into the structured report format defined in `docs/DESIGN.md` §6. Refuses to generate a report — or clearly marks it incomplete — when evidence sufficiency isn't met. Report language avoids accusatory framing (`docs/AI_SAFETY_AND_GUARDRAILS.md`).

## F8. Human Review & Decision Workflow

**Phase:** MVP · **Module:** `review`

Implements Approve / Reject / Request More Info / Escalate actions (`docs/DESIGN.md` §5), each requiring an authenticated, RBAC-authorized human and producing an `audit_events` record. This is the only path by which case disposition changes.

## F9. Audit Trail

**Phase:** MVP · **Module:** `audit`

Append-only logging of every agent run, tool call, and human decision (`docs/DATABASE_SCHEMA.md` §4.17, `docs/OBSERVABILITY_AND_AUDIT.md`). Exposed in the UI as an expandable per-case timeline.

## F10. Basic Risk Scoring

**Phase:** MVP (prototype tier) → Phase 2 (calibrated) · **Module:** `risk_engine`

MVP: a simple, clearly labeled PROTOTYPE scoring combining a handful of signals (per `docs/EVALUATION.md` methodology labeling requirement — never presented as production-calibrated). Phase 2: replace with an experimentally validated model with documented methodology, evaluation, and thresholds.

## F11. Specialized Agents — Sanctions/Watchlist Screening

**Phase:** Phase 2 · **Module:** `agents.sanctions` (new)

Screens customer/counterparty names against a synthetic/public watchlist dataset. Read-only. Follows the same agent documentation pattern as `docs/ARCHITECTURE.md` §4. Not built until Phase 2 — do not scaffold prematurely.

## F12. Adverse Media Analysis

**Phase:** Phase 2 · **Module:** `agents.adverse_media` (new)

Retrieves and summarizes (via RAG over a curated/synthetic corpus — **never live open-web scraping of real individuals**, to avoid conflating synthetic personas with real people) adverse-media-style signals. Deferred; design details TBD at Phase 2 kickoff.

## F13. Entity Resolution

**Phase:** Phase 2 · **Module:** `agents.graph` (extended) / `retrieval`

Improves graph quality by resolving near-duplicate entities (e.g., same person across slightly different records) within the synthetic dataset. Deferred; approach (rule-based vs. ML-based) to be decided via ADR at Phase 2 kickoff.

## F14. Improved Risk Scoring & Calibration

**Phase:** Phase 2/3 · **Module:** `risk_engine`

Replaces prototype weights with a model trained/validated against labeled synthetic patterns (AMLSim/Elliptic labels where applicable), with documented methodology, calibration, and monitoring (`docs/EVALUATION.md`).

## F15. RBAC & Authorization Hardening

**Phase:** Phase 3 · **Module:** `identity`

Full role-based access control across case visibility, approval authority, and admin functions (`docs/SECURITY.md` §"Authorization Model").

## F16. Observability Stack (OpenTelemetry, dashboards)

**Phase:** Phase 3 · **Module:** cross-cutting

Structured tracing across agent chains, dashboards for reliability/latency (`docs/OBSERVABILITY_AND_AUDIT.md`).

## F17. Evaluation Harness

**Phase:** Phase 3 (framework), ongoing thereafter · **Module:** cross-cutting, `docs/EVALUATION.md`

Automated measurement of ML, RAG, agent, system, and human-comparison metrics against the synthetic fixture set. Must produce real, reproducible numbers — never narrative-only claims.

## F18. Advanced Research Features (temporal graphs, GNNs, red-teaming)

**Phase:** Phase 4 · **Module:** research spike, not core system

Explicitly research-tier; not required for the core product story. Only pursued if it can be done with real evaluation, per `CLAUDE.md` §10.

---

## Feature-to-Document Cross-Reference

| Feature | Architecture | Schema | Security | Safety | Evaluation | Testing |
|---|---|---|---|---|---|---|
| F1–F2 | §2, §5 | `cases`,`alerts`,`investigation_runs` | Trust boundaries | — | System metrics | Integration |
| F3–F5 | §4 | `transactions` etc., `document_chunks` | Tool permissions | Evidence-first | ML/RAG metrics | Unit + fixtures |
| F6–F7 | §4.5 | `evidence`,`findings` | Data leakage | No-unsupported-conclusions | Agent metrics | Safety-critical tests |
| F8–F9 | §7 | `audit_events` | AuthZ | Human-in-loop | Human eval | E2E |
| F10, F14 | `risk_engine` | `risk_signals` | — | Risk-score labeling rules | ML metrics | Regression |
| F11–F13 | Phase 2 additions | new tables TBD | Least privilege | Evidence-first | Agent metrics | Fixtures TBD |
| F15–F17 | §3, §9 | `users`/`roles` | Full model | — | System/agent metrics | Security + E2E |
