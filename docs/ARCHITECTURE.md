# System Architecture — Project Meridian

**Read every coding session?** Yes, for the relevant component(s).

---

## 1. Architecture Philosophy

Meridian is built as a **modular monolith** for the MVP and Phase 2, not a microservices/event-streaming system. This is a deliberate deviation from the original brief's suggested stack (see `docs/DECISIONS.md` and ADR-0001). Rationale:

- A single deployable backend with clearly separated internal modules is easier to reason about, test, and audit for a project of this scope.
- Kafka, multiple databases, and container-orchestrated microservices add operational complexity that isn't justified until there's a demonstrated throughput/scaling requirement (there isn't one — this is a single-analyst-workbench-scale portfolio system).
- Module boundaries are kept clean enough (see §3) that a future split into services is possible without a rewrite, if ever justified (see `docs/ROADMAP.md` Phase 4).

**PROPOSAL** (not yet implemented, subject to revision as the project develops): the specific module layout below.

---

## 2. High-Level Architecture

```
                        ┌─────────────────────┐
                        │   Frontend (Web)     │
                        │  Investigation UI     │
                        └──────────┬───────────┘
                                   │ HTTPS/REST
                        ┌──────────▼───────────┐
                        │   FastAPI Backend      │
                        │  AuthN/AuthZ (RBAC)    │
                        └──────────┬───────────┘
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                 ▼
         Case Management   Investigation       Admin/Audit
            Service          Orchestrator          API
                                   │
                  ┌────────────────┼────────────────┐
                  ▼                ▼                 ▼
           ML Risk Engine     Agent Layer      Retrieval Layer
           (scikit-learn/     (least-priv.     ┌──────┴──────┐
            XGBoost, batch/    tool-scoped      ▼             ▼
            on-demand)         agents)     Structured DB   Document RAG
                                   │        (PostgreSQL)   (pgvector +
                  ┌────────────────┼────────────────┐       BM25 hybrid)
                  ▼                ▼                 ▼
           Transaction        Graph              Policy/
             Agent            Agent            Compliance
          (read-only SQL)  (read-only graph      Agent
                             queries over        (read-only RAG)
                             PostgreSQL views)
                                   │
                          Evidence & Findings Store
                                   │
                          Report Generation Agent
                                   │
                          Human Review / Approval
                                   │
                            Audit Log (append-only)
```

All AI/DB/agent activity is written to the append-only audit log (`docs/OBSERVABILITY_AND_AUDIT.md`). Redis is used only for orchestration state/caching (§6), not as a system of record.

---

## 3. Module Boundaries (Modular Monolith)

| Module | Responsibility | Owns Data |
|---|---|---|
| `case_management` | Alert intake, case lifecycle, analyst assignment | `cases`, `alerts` |
| `orchestration` | Investigation workflow control, agent/tool dispatch, evidence-sufficiency gating | `investigation_runs`, `agent_runs` |
| `agents.transaction` | Transaction anomaly/behavioral analysis (read-only SQL) | — (reads `transactions`, `accounts`) |
| `agents.graph` | Entity/transaction graph construction & analysis (read-only) | — (reads `transactions`, `entities`, `graph_relationships`) |
| `agents.policy` | Policy/regulatory retrieval via RAG (read-only) | — (reads `documents`, `document_chunks`) |
| `agents.report` | Evidence-backed report synthesis; enforces no-unsupported-conclusions rule | `findings`, `recommendations` |
| `risk_engine` | ML-based anomaly/risk scoring (batch and on-demand) | `risk_signals` |
| `evidence` | Canonical evidence records linking findings to source data | `evidence` |
| `review` | Human approval workflow, decision capture | human decision fields on `cases`/`investigation_runs` |
| `audit` | Append-only logging of all agent/tool/human actions | `audit_events` |
| `identity` | AuthN/AuthZ, RBAC | users/roles (see `docs/DATABASE_SCHEMA.md`) |
| `retrieval` | Hybrid retrieval (BM25 + vector) shared library used by `agents.policy` | — |

Each module exposes a narrow internal interface; other modules must not reach into another module's tables directly except through its interface. This is enforced by code review discipline (documented here) rather than physical service separation, given the modular-monolith choice — **ASSUMPTION**: this discipline is sufficient at current project scale; revisit if the codebase grows past what one team can review effectively.

---

## 4. Agent Architecture

Per `CLAUDE.md` §6, every agent is documented here with responsibility, inputs/outputs, tools, permissions, and failure behavior.

### 4.1 Orchestrator (not itself an "agent" with an LLM persona — a deterministic controller with LLM-assisted planning)

- **Responsibility:** Determine investigation state; decide which agents/tools are necessary for a given alert; enforce evidence-sufficiency and permission rules; handle agent failures; prevent report generation on incomplete/unsupported investigations; maintain traceability.
- **Inputs:** Alert record, case state.
- **Outputs:** `investigation_run` record, dispatch instructions to agents, final gating decision on whether a report may be generated.
- **Tools:** Read access to `cases`/`alerts`; write access to `investigation_runs`/`agent_runs`.
- **Failure behavior:** On repeated agent failure, terminate the workflow and flag the case for human triage rather than producing a partial/unsupported report.
- **Design intent:** does not blindly invoke every agent for every case — it selects agents based on alert type and evolving evidence (**PROPOSAL** — selection logic to be implemented incrementally starting with a simple rule-based dispatch table in the MVP, revisited for LLM-assisted planning in Phase 2).

### 4.2 TransactionAgent
- **Responsibility:** Analyze the alerted customer's transaction history for anomalies (amount deviation, velocity, new counterparties).
- **Inputs:** customer ID, account ID(s), alert transaction ID.
- **Outputs:** Derived signals (e.g., "16.3× historical average") with links to source transaction rows.
- **Tools:** Read-only SQL query tool scoped to `transactions`, `accounts`, `customers` (parameterized queries only — no free-form SQL execution from LLM output; see `docs/SECURITY.md`).
- **Permissions:** Read-only.
- **Failure behavior:** If a required aggregate cannot be computed (e.g., insufficient history), return `UNKNOWN` for that signal, not an estimate.

### 4.3 GraphAgent
- **Responsibility:** Build and analyze the transaction/entity graph around the alerted customer (community/centrality/pattern detection using NetworkX).
- **Inputs:** customer/account ID, hop-depth limit.
- **Outputs:** Subgraph structure, flagged patterns (e.g., rapid pass-through), links to underlying transaction/relationship rows.
- **Tools:** Read-only graph-construction queries over PostgreSQL (`graph_relationships`, `transactions`); in-process NetworkX analysis.
- **Permissions:** Read-only.
- **Failure behavior:** Bounded hop-depth and node-count limits to prevent runaway queries; on limit-exceeded, return a partial graph explicitly marked as partial.

### 4.4 PolicyAgent
- **Responsibility:** Retrieve relevant internal AML policy / regulatory guidance passages for the case's alert pattern.
- **Inputs:** Alert type/pattern description, jurisdiction (where applicable).
- **Outputs:** Retrieved chunks with source document ID, version, and relevance/confidence score.
- **Tools:** Hybrid retrieval (PostgreSQL FTS + pgvector cosine distance, fused via Reciprocal Rank Fusion) read-only. Embedding model: BAAI/bge-small-en-v1.5 (per ADR-0004).
- **Permissions:** Read-only.
- **Failure behavior:** If retrieval confidence is below threshold, return no policy citation rather than a low-confidence guess (`docs/EVALUATION.md` defines the threshold methodology).

### 4.5 ReportAgent
- **Responsibility:** Synthesize findings from other agents into the structured Fact→Signal→Interpretation→Recommendation report; enforce the no-unsupported-conclusions rule.
- **Inputs:** All evidence/findings produced in the investigation run.
- **Outputs:** `findings`, `recommendations`, draft report.
- **Tools:** Read access to evidence/findings store; write access limited to draft report fields (not case disposition).
- **Permissions:** No write access to case status, account status, or any downstream system.
- **Failure behavior:** If evidence coverage for a candidate finding is insufficient, omit or explicitly flag that finding as unsupported rather than including it.

### 4.6 CaseAgent (case-note support, Phase 2)
- **Responsibility:** Assist analysts with controlled case-note operations (e.g., drafting a note for analyst review before it's saved).
- **Tools:** Controlled write access to `case_notes` — writes always attributed to and confirmed by the human analyst; the agent never writes autonomously without a human-confirmed action.
- **Permissions:** Write, but only via a human-confirmed action, never silently.

### 4.7 Sanctions/Watchlist and Adverse-Media Agents (Phase 2, PROPOSAL)
Deferred to Phase 2. Will follow the same documentation pattern above once designed; not implemented in MVP. Do not build ahead of `docs/ROADMAP.md`.

---

## 5. Orchestrator Decision Logic (MVP)

**PROPOSAL for MVP implementation:**

```
1. Receive alert → create investigation_run
2. Always run: TransactionAgent (every alert has a transaction to analyze)
3. If alert involves a new/rare counterparty or graph depth > 1 signal → run GraphAgent
4. Always run: PolicyAgent (every investigation needs applicable-policy context)
5. Evaluate evidence sufficiency:
   - If TransactionAgent and PolicyAgent both returned usable evidence → proceed to ReportAgent
   - If critical evidence missing (e.g., TransactionAgent returned UNKNOWN for the primary signal) → flag investigation_run as INCOMPLETE, do not generate report, notify analyst
6. ReportAgent synthesizes findings; if no findings meet evidence bar → report states "insufficient evidence," not a fabricated conclusion
7. Route to human review queue
```

This is intentionally simple for MVP (rule-based dispatch) rather than a free-form LLM planner, per `CLAUDE.md` §10 ("do not over-engineer the MVP"). LLM-assisted dynamic planning is a Phase 2+ candidate, to be justified via ADR before implementation.

---

## 6. Technology Selection

Each choice below is evaluated against the brief's suggested stack, not accepted by default.

| Technology | Decision | Why | MVP? | Alternatives considered |
|---|---|---|---|---|
| Python + FastAPI | **Adopted** | Mature async web framework, strong typing support, wide ecosystem for ML/AI integration | Yes | Django (heavier than needed), Flask (weaker async/typing story) |
| PostgreSQL | **Adopted** | Single relational store for structured data, graph edges (via adjacency tables), and vectors (via pgvector) — avoids introducing a second database for the MVP | Yes | Separate graph DB (Neo4j) — deferred, see ADR-0002 |
| pgvector | **Adopted** | Keeps vector search inside the existing PostgreSQL instance instead of adding a dedicated vector DB | Yes | Dedicated vector DB (Pinecone/Weaviate) — unjustified at this scale |
| Redis | **Adopted, narrow scope** | Orchestration run-state caching and short-lived locks only; not a system of record | Yes (minimal) | In-process state (rejected — needed across worker restarts for long-running investigations) |
| Kafka | **Rejected for MVP/Phase 2** | No demonstrated throughput/streaming requirement; alerts arrive at analyst-workbench scale, not real-time firehose scale, for this project | No | Direct DB-triggered/queue-based processing (simple background job) suffices |
| LangGraph (or equivalent orchestration framework) | **Deferred — MVP uses a hand-written orchestrator** | A framework adds a layer of abstraction that isn't justified while the dispatch logic is a simple rule table (§5); revisit once dynamic multi-agent planning is actually needed (Phase 2) | No | Hand-rolled orchestrator (adopted for MVP) |
| NetworkX | **Adopted** | Sufficient for in-process graph construction/analysis at this data scale; no need for a distributed graph engine | Yes | Neo4j (deferred, ADR-0002), igraph (comparable, NetworkX chosen for Python-native ergonomics) |
| Neo4j | **Deferred** | Only justified if graph complexity/scale outgrows PostgreSQL-adjacency + NetworkX — not true for MVP synthetic dataset sizes | No (Phase 2/3 candidate) | — |
| scikit-learn / XGBoost | **Adopted** | Standard, well-understood tools for tabular anomaly/risk models; appropriate for structured financial data per brief §7.1 | Yes (Phase 1 for basic model, iterated Phase 2) | PyTorch — deferred unless a deep-learning approach (e.g., autoencoder or GNN) is specifically justified (Phase 4) |
| PyTorch | **Deferred to Phase 4** | Only justified for GNN/temporal-graph research work, which is explicitly a Phase 4 (Advanced Research) concern | No | — |
| React/Next.js | **Adopted for investigation workspace UI** | Needed for the multi-panel investigation workspace UX (`docs/DESIGN.md`); a Streamlit MVP is an acceptable interim per brief, but the target UX (graph view, evidence panels, review controls) benefits from a real frontend framework | Phase 1 interim: Streamlit acceptable; target: React | Streamlit-only (rejected long-term — insufficiently flexible for the target UX) |
| Docker | **Adopted** | Standard local-dev/deployment reproducibility | Yes | — |
| OpenTelemetry | **Adopted, introduced in Phase 3** | Structured tracing valuable for auditability of agent chains, but full observability stack (Prometheus/Grafana) is Phase 3 "Production Readiness" scope, not MVP | No (MVP uses structured logging only; OTel in Phase 3) | — |
| LLM Provider | **Abstracted behind an interface (ADR-0003 required before locking in a specific provider)** | Avoid hard-coupling to one vendor's SDK; provider swap should not require rewriting agent logic | Yes (interface), provider choice per ADR | Direct SDK coupling — rejected |

**Do not introduce Kafka, Kubernetes, Neo4j, multiple databases, or additional microservices without a new ADR justifying a demonstrated requirement.**

---

## 7. Data Flow Summary

1. Alert ingestion → `case_management` creates `cases`/`alerts` row.
2. Orchestrator creates `investigation_runs`, dispatches agents per §5.
3. Agents read via their scoped tools only; each agent invocation is recorded as an `agent_runs` row and relevant `audit_events`.
4. Findings/evidence are written to `findings`/`evidence`, always with a source reference.
5. ReportAgent assembles the report from `findings`/`evidence`/`recommendations`; gated by evidence-sufficiency check.
6. Report enters human review (`review` module); human decision is recorded and is the only thing capable of changing case disposition.
7. All of the above is written to the append-only `audit_events` table (`docs/OBSERVABILITY_AND_AUDIT.md`).

---

## 8. Non-Functional Priorities

Per `CLAUDE.md` §10, in priority order for this project: **correctness/evidence-integrity > auditability > security > testability > maintainability > raw performance**. Do not trade the first three for speed or scale the project doesn't need.

---

## 9. Related Documents

`docs/DATABASE_SCHEMA.md` (data model detail), `docs/SECURITY.md` (trust boundaries), `docs/AI_SAFETY_AND_GUARDRAILS.md` (agent behavioral constraints), `docs/DECISIONS.md` (ADR index), `docs/ROADMAP.md` (phased build-out).
