# Observability, Logging & Audit — Project Meridian

**Read every coding session?** Yes, for any change to agent execution, tool calls, or case-decision workflows.

---

## 1. Purpose

Every material investigation action must be reproducible and auditable after the fact — an investigator, reviewer, or (in this project's context) a technical reviewer evaluating the portfolio project must be able to answer "why did the system produce this finding/recommendation?" from logged data alone, without needing to re-run anything or trust an unverifiable narrative.

---

## 2. What Gets Captured

For every agent/tool invocation and every human decision, capture (fields map to `audit_events` and `agent_runs`, `docs/DATABASE_SCHEMA.md` §4.11/§4.17):

- Case ID / Investigation Run ID
- Agent name (or "human" for human actions)
- Tool invoked (if applicable)
- Timestamp
- Input (redacted per `docs/SECURITY.md` §4)
- Query / tool invocation detail (e.g., which parameterized query, which retrieval query)
- Output (redacted, summarized if large)
- Evidence references produced
- Model identifier (which LLM/model, if any, was used)
- Prompt/template version identifier
- Policy/document version referenced (for RAG-backed findings)
- Errors (full error detail server-side; redacted summary in any user-facing view)
- Human decisions (who, what action, when, and any required reason text)

**Do not log more than necessary.** PII and sensitive values are redacted at the logging boundary (`docs/SECURITY.md` §4), not left to individual call sites to decide inconsistently.

---

## 3. Logging Levels (MVP — structured logging; OpenTelemetry added Phase 3)

MVP uses structured (JSON) application logs plus the `audit_events` table as the durable, queryable audit record. Phase 3 adds distributed tracing (OpenTelemetry) so a full investigation's agent chain can be visualized as a trace, and dashboards (latency, failure rate, agent success rate) per `docs/ROADMAP.md`.

**REQUIRES VERIFICATION at implementation time:** exact logging library/config — read the actual repo config rather than assuming.

---

## 4. Audit Log Integrity

- `audit_events` is append-only at the database-grant level (no `UPDATE`/`DELETE` for the application role) — see `docs/DATABASE_SCHEMA.md` §4.17.
- Every case-disposition-changing action (`docs/DESIGN.md` §5) must produce exactly one corresponding `audit_events` row before the case status is considered changed — i.e., the audit write and the state transition should be in the same transaction, not eventually-consistent, so an approval can never happen without a corresponding audit record.

---

## 5. Reproducibility

Given a `case_id`, it must be possible to reconstruct:
1. What alert triggered the case.
2. Which agents ran, in what order, with what inputs.
3. What evidence each agent produced, and what source rows that evidence points to.
4. What the ReportAgent synthesized and why (which findings, at what confidence).
5. What the human reviewer decided and when.

This reconstruction should be achievable by querying `audit_events` + `agent_runs` + `evidence` + `findings`, joined on `investigation_run_id` — this is a concrete testable property, not just an aspiration (see `docs/TESTING.md`).

---

## 6. What This Enables (and doesn't)

This system makes it possible to detect *after the fact* that an unsupported claim slipped through, a permission boundary was violated, or a human decision wasn't properly recorded. It does not, by itself, prevent every possible failure — prevention comes from the combination of this logging, the evidence-sufficiency gate (`docs/AI_SAFETY_AND_GUARDRAILS.md`), tool permission enforcement (`docs/SECURITY.md`), and testing (`docs/TESTING.md`). Do not claim the audit system alone guarantees correctness.

---

## 7. Related Documents

`docs/SECURITY.md` §"Data Retention & Redaction", `docs/DATABASE_SCHEMA.md` §4.11/§4.17, `docs/AI_SAFETY_AND_GUARDRAILS.md` (what triggers a logged failure state), `docs/TESTING.md` (reproducibility test cases).
