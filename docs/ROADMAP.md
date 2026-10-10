# Implementation Roadmap — Project Meridian

**Read every coding session?** Reference document — check the current phase before proposing new scope.

---

## Phase 0 — Foundation

**Goal:** A working, documented, tested skeleton — nothing user-facing yet.

- Repository scaffold, this documentation system committed
- Coding standards / linter / formatter / type-checker configured
- Local development environment (Docker Compose: FastAPI app + PostgreSQL w/ pgvector)
- CI pipeline: lint, type-check, unit tests on every PR
- Security baseline: secrets management approach, dependency scanning
- Initial migrations for core tables (§ per `docs/DATABASE_SCHEMA.md` §4.1–4.9, 4.17–4.18)

**Exit criteria:** CI green on an empty-but-structured repo; a health-check endpoint deployed locally via Docker; schema migrations apply cleanly to a fresh DB.

**Dependencies:** none.

---

## Phase 1 — MVP

**Goal:** End-to-end single-investigation flow on synthetic data, human-reviewable, fully auditable.

Scope (maps to Features F1–F10 in `docs/FEATURES.md`):
- Customer/account/transaction data loaded from AMLSim/PaySim synthetic sources (`docs/DATA_AND_DATASET_STRATEGY.md`)
- Alert generation (synthetic monitoring generator) or alert import
- Transaction anomaly detection (TransactionAgent, rule/statistics-based)
- Basic transaction graph (GraphAgent, bounded-depth, NetworkX)
- Single rule-based investigation orchestrator
- Policy RAG (PolicyAgent) over a small curated/synthetic policy corpus
- Evidence collection and linking
- Investigation report generation with evidence-sufficiency gating
- Human approval UI (Streamlit acceptable per `docs/DESIGN.md` §8)
- Full audit trail (append-only)
- Prototype-tier risk scoring, clearly labeled as such

**Exit criteria:** The worked example from `docs/PRODUCT_BRIEF.md` §5 runs end-to-end — alert in, evidence-backed report out, human decision recorded, full audit trail reconstructable. At least the safety-critical tests in `docs/TESTING.md` (no-unsupported-conclusion path, evidence-sufficiency gate) pass.

**Dependencies:** Phase 0 complete.

---

## Phase 2 — Investigation Intelligence

**Goal:** Deepen investigative capability; still not production-hardened.

Scope (Features F11–F14):
- Specialized agents: Sanctions/Watchlist Agent, Adverse Media Agent
- Entity resolution
- Stronger graph analytics (community detection, centrality)
- Improved hybrid retrieval (reranking)
- Risk scoring: documented methodology plus measured per-signal evaluation (PROTOTYPE); composite calibration gated on ADR-0005 G1.
- React-based investigation workspace UI: DEFERRED.

**Exit criteria:** Each new agent documented per `docs/ARCHITECTURE.md` §4 pattern before merge; risk scoring methodology and evaluation numbers published in `docs/EVALUATION.md` (not just claimed); ADRs recorded for entity-resolution approach and any retrieval architecture change.

**Dependencies:** Phase 1 complete; risk-scoring calibration depends on having a labeled synthetic fixture set (`docs/DATA_AND_DATASET_STRATEGY.md`).

### Phase 2 kickoff notes (recorded 2026-10-01)

**Phase 1 baseline.** Phase 2 was scoped against commit `9165deb` ("feat(phase1): surface computed risk signals and verify e2e flow"), contained in `main` via merge commit `d6b22ed` (PR #24). This document does not itself declare the Phase 1 exit criteria met; that assessment is not recorded here.

**Execution model.** The Phase 2 scope list above is unordered. The relationships below are a partial order, not a linear sequence. "Hard" means a dependency stated in this roadmap or its referenced documents. "Soft" and all tie-breaks are ASSUMPTION/PROPOSAL, not repository requirements.

| Capability | Hard prerequisite (documented) | Soft dependency (ASSUMPTION) |
|---|---|---|
| Labeled evaluation fixture foundation (enabling task added at kickoff; not a scope bullet above) | Phase 1 baseline | none |
| Calibrated risk scoring | Labeled synthetic fixture set (Dependencies line above; `docs/EVALUATION.md` §2) | Additional deterministic risk signals (see open decision A/B) |
| Entity resolution | ADR for the approach (exit criteria above) | Planted near-duplicate fixtures |
| Stronger graph analytics | none documented | Planted-subgraph fixtures (`docs/EVALUATION.md` §3); entity resolution |
| Sanctions/watchlist agent (F11) | Agent documented per `docs/ARCHITECTURE.md` §4 before merge; design and tables TBD (`docs/FEATURES.md`) | Verified dataset license (EXTERNAL); entity resolution |
| Adverse media agent (F12) | Agent documented per `docs/ARCHITECTURE.md` §4 before merge; design TBD (`docs/FEATURES.md`) | Retrieval reranking |
| Retrieval reranking | ADR if retrieval architecture changes (exit criteria above); labeled query set (`docs/EVALUATION.md` §4) | none |
| React investigation workspace | none documented | Outputs of new Phase 2 agents |

**Recorded order.** (1) Task 0: this documentation kickoff. (2) Task 1: labeled evaluation fixture foundation v0.1, before any calibration work. (3) Everything else is unordered by the repository; the tie-break PROPOSAL is: calibration, then entity resolution, then graph analytics and sanctions, then reranking and adverse media, then the React workspace. Design and ADR work on independent items may proceed in parallel.

**Open decisions (unresolved as of this note).**
- A/B resolved in favor of B (bounded): add deterministic signals already documented for the TransactionAgent (`docs/ARCHITECTURE.md` §4.2, `docs/FEATURES.md` F3) one slice at a time, then calibrate the expanded signal set; any calibration claim must name the signal-set version.
- `orchestrator_version`: removed from `docs/DATABASE_SCHEMA.md` §4.10; no migration or code uses one. Revisit only with a concrete reproducibility requirement.
- Risk-scoring approach: ADR-0005 Accepted; D4 decided option (a) (re-scoped to documented methodology plus measured per-signal evaluation, PROTOTYPE); composite calibration remains gated on ADR-0005 G1.
- Entity-resolution approach: ADR-0006 (Accepted). D5 (persistent storage) is deferred. The immediate constraint remains that ER evaluation requires planted variants/ground truth.

### Phase 2 status and re-scoping (recorded 2026-10-05)

- **What exists:** deterministic transaction signals (amount deviation, transaction velocity, and beneficiary age wired), graph structure signals (graph cycle length and outbound chain depth wired), ER first slice (ADR-0006 D1, computation-only, unwired, D5 deferred), per-signal baselines, ADR-0005/0006/0007.
- **Branch status:** Tasks 17–20 merged to `main` (verified tip: `0289b95`).
- **Maintainer decision (Post-Task 21 order):** F11 sanctions/watchlist design/ADR first, then F11 implementation, then RAG evaluation.
- **Re-scoped/deferred:**
  - Community detection and centrality DEFERRED (optional; no exit criterion depends on it; would need a new planted-community corpus).
  - Retrieval reranking REPLACED by RAG evaluation (labeled query set plus calibration of the PolicyAgent threshold per docs/EVALUATION.md §4; reranking only if measurement shows a gap; any retrieval architecture change requires an ADR).
  - Adverse-media agent (F12) DEFERRED (design TBD, corpus too small to evaluate).
  - Sanctions/watchlist agent (F11) REMAINS IN SCOPE, synthetic watchlist only, design/ADR before code.
  - React workspace DEFERRED: Streamlit remains the UI through Phase 3; React stays a documented option, not a scheduled item.
  - Authentication hardening (F15): pulled forward and implemented at DEMO grade (opaque bearer tokens), not production IAM.
- **Phase 3 applicability notes:** model monitoring N/A until a calibrated model exists; LLM retry/backoff N/A while no LLM exists; OpenTelemetry optional.

### Phase 2 status update (recorded 2026-10-10)

- **ADR-0008 and Task 23 foundation:** ADR-0008 accepted. The deterministic synthetic-watchlist foundation (Task 23) is implemented: schema migration `4573f3e20e1c` (`watchlist_entries`), atomic privileged loader, read-only version reader, exact normalized-name candidate matcher (`exact_norm_name_v1`), in-memory synthetic corpus, and candidate-generation fidelity baseline (PROTOTYPE).
- **Status is UNWIRED:** The foundation remains unwired into runtime pipelines. Not done: `screening_results` table, `SanctionsAgent` dispatch, orchestrator wiring, report/authoring, audit-trail extension, and UI integration.
- **Task sequencing:** ADR-0008 implementation sequencing references Task 24 as a non-binding guide, not an authorization to begin. The post-Task 21 maintainer order is preserved: F11 implementation, then RAG evaluation.
- **Contract status:** The exception-based reader and matcher API shape is provisionally accepted pending a maintainer decision on the typed-result contract.
- **Regression evidence:** Full database-enabled test suite verified with zero skips (472 passed, 0 skipped, 0 failed), superseding earlier offline results with missing database environment variables.

---

## Phase 3 — Production Readiness

**Goal:** Make the system defensible as "engineered like it could be real," within the honest limits of a portfolio project.

Scope (Features F15–F17):
- Observability: OpenTelemetry tracing across agent chains, structured dashboards
- Security hardening: full threat-model pass against `docs/SECURITY.md`, dependency/secret scanning in CI, prompt-injection test suite
- Evaluation framework: automated, reproducible ML/RAG/agent/system/human-comparison metrics (`docs/EVALUATION.md`)
- Model monitoring: drift/quality checks on risk scoring
- Reliability: retry/backoff, graceful degradation for LLM/tool failures
- Full RBAC across roles
- Data governance: retention/redaction enforcement, documented data lineage
- Deployment automation (containerized, reproducible deploy)

**Exit criteria:** Security review checklist (`docs/SECURITY.md`) passes; evaluation harness produces real numbers across all five categories in `docs/EVALUATION.md`; RBAC enforced and tested for all four human-decision actions.

**Dependencies:** Phase 2 complete.

---

## Phase 4 — Advanced Research (optional, exploratory)

**Goal:** Research-tier extensions, pursued only if time/interest allows and only with real evaluation attached — not required for the core portfolio narrative.

Scope (Feature F18):
- Temporal graph models
- Graph Neural Networks, where justified by a concrete detection gap not addressable by Phase 2 graph analytics
- Advanced anomaly detection (e.g., autoencoder-based)
- Investigation planning (LLM-assisted dynamic orchestration, replacing the Phase 1 rule-based dispatcher — would need its own ADR)
- Counterfactual explanations for risk scores
- Automated red-teaming / adversarial prompt-injection testing
- Advanced agent trajectory evaluation

**Exit criteria:** Each item requires its own scoped evaluation before being claimed as a project result — no "we explored GNNs" without actual precision/recall numbers on the synthetic fixture set.

**Dependencies:** Phase 3 complete. This phase is explicitly optional and should not be started while Phase 1–3 exit criteria remain unmet.

---

## Cross-Phase Rule

No phase's "advanced" features should be pulled forward merely because they'd look impressive in a demo. `CLAUDE.md` §9 (Change Management) governs any request to jump phases — the conflict must be raised and a decision made explicitly, not silently absorbed.
