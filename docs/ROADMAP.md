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
- Calibrated risk scoring (replacing prototype weights) with documented methodology and evaluation
- React-based investigation workspace UI (superseding Streamlit interim), including the full graph view and timeline panels from `docs/DESIGN.md`

**Exit criteria:** Each new agent documented per `docs/ARCHITECTURE.md` §4 pattern before merge; risk scoring methodology and evaluation numbers published in `docs/EVALUATION.md` (not just claimed); ADRs recorded for entity-resolution approach and any retrieval architecture change.

**Dependencies:** Phase 1 complete; risk-scoring calibration depends on having a labeled synthetic fixture set (`docs/DATA_AND_DATASET_STRATEGY.md`).

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
