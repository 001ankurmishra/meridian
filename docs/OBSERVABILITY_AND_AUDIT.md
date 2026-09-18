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

**F8 Human Decision Audit Shape:**
For human decisions, the `input_summary` MUST contain:
- `decision`: The requested action (e.g. "APPROVE", "REJECT", "REQUEST_MORE_INFO", "ESCALATE")
- `reason`: The justification text provided by the analyst (required for REJECT/REQUEST_MORE_INFO)
The `output_summary` MUST contain:
- `previous_status`: The case status prior to the decision
- `new_status`: The case status after the decision

**F9 `tool_calls` Convention:**
`agent_runs.tool_calls` is populated by the dispatch layer (`orchestration.transaction_agent_dispatch`, `orchestration.policy_agent_dispatch`) with a coarse, static, per-agent-run summary of the tool(s)/quer(ies) that agent is documented to invoke — not a live, per-statement trace of an individual invocation. `orchestration.agent_run_tracking.record_agent_run()` accepts this as an explicit keyword-only `tool_calls` argument (`None` default, stored as an empty object) and never fabricates a value on its own; only a caller with direct knowledge of what the wrapped function does may supply one.

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

**F9 implementation:** points 2, 3, and 5 above are implemented by `audit.audit_trail.get_case_audit_trail(engine, case_id)` (`src/meridian/audit/audit_trail.py`), which assembles a case's `investigation_runs` (each with its nested `agent_runs`, `evidence`, and `findings`, chronologically ordered) plus the case's `audit_events` (human decisions), all in one read-only call. It performs no writes and no authorization check — same authentication-boundary framing as `review.decisions.record_human_decision` (`docs/SECURITY.md`): it must not be exposed as an unauthenticated API boundary. It is a best-effort, point-in-time snapshot assembled from several independent `SELECT`s, not a single transactional read, so it is not guaranteed atomic against concurrent writes.

**Known coverage gap (as of F9):** `agent_runs` — and therefore this reconstruction — only includes agents actually wrapped by `orchestration.agent_run_tracking.record_agent_run()`. As of this writing, only `TransactionAgent` (F3) and `PolicyAgent` (F5) are wrapped this way; `GraphAgent` (F4) and `ReportAgent` (F7) are not currently dispatched through `record_agent_run()` and so produce no `agent_runs` row — their executions are invisible to `get_case_audit_trail()` even when they ran as part of an investigation. Point 4 above (ReportAgent's synthesis) is therefore not yet reconstructable via this path. Closing this gap is an F4/F7 completeness item, out of scope for F9.

Point 1 (which alert triggered the case) is not currently included in `get_case_audit_trail()`'s output — it can be obtained separately via `cases.alert_id` — and may be folded in by a future slice if a single combined view is needed.

---

## 6. What This Enables (and doesn't)

This system makes it possible to detect *after the fact* that an unsupported claim slipped through, a permission boundary was violated, or a human decision wasn't properly recorded. It does not, by itself, prevent every possible failure — prevention comes from the combination of this logging, the evidence-sufficiency gate (`docs/AI_SAFETY_AND_GUARDRAILS.md`), tool permission enforcement (`docs/SECURITY.md`), and testing (`docs/TESTING.md`). Do not claim the audit system alone guarantees correctness.

---

## 7. Related Documents

`docs/SECURITY.md` §"Data Retention & Redaction", `docs/DATABASE_SCHEMA.md` §4.11/§4.17, `docs/AI_SAFETY_AND_GUARDRAILS.md` (what triggers a logged failure state), `docs/TESTING.md` (reproducibility test cases).
