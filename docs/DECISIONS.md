# Architecture Decision Records — Index & Process

**Read every coding session?** Conditionally — yes when a change touches an area with an existing ADR, or when a change is itself architecturally significant.

---

## 1. Purpose

Important, hard-to-reverse decisions are recorded as ADRs under `docs/decisions/` so that future sessions (human or AI) understand *why* something is the way it is, not just what it currently is. This directly supports `CLAUDE.md`'s anti-drift goal: an agent must not silently make a major architectural decision — it proposes, the human decides, and the decision is recorded.

---

## 2. When to Write an ADR

Write one for decisions such as: modular monolith vs. microservices, choice of (or against) a separate graph database, vector-search architecture, orchestration framework choice, LLM provider abstraction approach, the evidence data model, risk-scoring approach, event-driven vs. request/response architecture, authentication model — and any other decision that would be expensive to reverse or that materially changes a `docs/ARCHITECTURE.md` position.

Do **not** write an ADR for routine implementation choices (variable naming, which test framework helper to use, minor refactors).

---

## 3. ADR Format

```
# ADR-XXXX: <Title>

Status: Proposed | Accepted | Superseded by ADR-YYYY
Date: <date>

## Context
What situation/problem prompted this decision.

## Decision
What was decided.

## Alternatives Considered
What else was evaluated and why it was not chosen.

## Consequences
What this makes easier, harder, or what it forecloses.
```

---

## 4. Current ADRs

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](decisions/0001-modular-monolith-vs-microservices.md) | Modular monolith vs. microservices | Accepted |
| [ADR-0002](decisions/0002-postgresql-vs-separate-graph-database.md) | PostgreSQL (+pgvector, adjacency tables) vs. a separate graph database | Accepted |
| [ADR-0003](decisions/0003-llm-provider-abstraction.md) | LLM provider abstraction | Proposed — provider not yet locked in |

Future ADRs (evidence model, risk-scoring approach, orchestration-framework revisit, authentication model, event-driven-architecture reconsideration) should be added under `docs/decisions/` and listed here as they are written, following `docs/ROADMAP.md` phase triggers (e.g., risk-scoring ADR is expected around Phase 2 calibration work).

---

## 5. Documentation Inventory

| File | Purpose | Read Every Coding Session? |
|---|---|---|
| `CLAUDE.md` | Master AI coding-agent instructions, anti-hallucination rules, session protocol | **Mandatory, always** |
| `docs/ARCHITECTURE.md` | System architecture, agent roles, tech selection | **Mandatory** for the relevant component |
| `docs/DATABASE_SCHEMA.md` | Data model | **Mandatory** for any data-touching change |
| `docs/DEVELOPMENT_RULES.md` | Engineering/coding rules | **Mandatory, always** |
| `docs/FEATURES.md` | Feature specification | **Mandatory** for the relevant feature area |
| `docs/SECURITY.md` | Security & trust boundaries | **Mandatory** for auth/data-access/agent-tool changes |
| `docs/AI_SAFETY_AND_GUARDRAILS.md` | Agent/report behavioral constraints | **Mandatory** for agent/report/risk-scoring changes |
| `docs/DECISIONS.md` + `docs/decisions/*` | ADR index and records | **Conditional** — check when touching an area with an existing ADR |
| `docs/PRODUCT_BRIEF.md` | Product definition | Conditional — product/feature work |
| `docs/PRODUCT_PRINCIPLES.md` | Product & AI principles | **Mandatory** for agent/report/risk-scoring changes |
| `docs/ROADMAP.md` | Phased implementation plan | Reference — check current phase before proposing new scope |
| `docs/DESIGN.md` | UX/interaction/report-format design | Conditional — frontend/report-formatting work |
| `docs/EVALUATION.md` | Evaluation strategy for ML/RAG/agent/system/human | Conditional — risk scoring, retrieval, or agent logic changes |
| `docs/OBSERVABILITY_AND_AUDIT.md` | Logging, tracing, audit requirements | **Mandatory** for agent execution / case-decision workflow changes |
| `docs/TESTING.md` | Full testing taxonomy and safety-critical tests | **Mandatory, always** (to determine required coverage) |
| `docs/DATA_AND_DATASET_STRATEGY.md` | Dataset sourcing, synthetic data rules, governance | Conditional — data ingestion/generation/fixture work |

---

## 6. Related Documents

`CLAUDE.md` §1 and §9 (when ADRs are required as part of change management).
