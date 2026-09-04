# AI Safety & Guardrails — Project Meridian

**Read every coding session?** Yes, for any change touching agent reasoning, report generation, or risk scoring.

This document defines the behavioral constraints for every AI component in Meridian, and how they are enforced in code (not just prompt instructions).

---

## 1. Prohibited Autonomous Actions (Hard Constraints)

No agent, orchestrator, or LLM call in this system may, on its own authority:

- Accuse a customer of criminal activity
- Declare that a customer is laundering money
- Freeze or close an account
- File a regulatory report (e.g., SAR-equivalent)
- Make a final suspicious-activity determination
- Take any irreversible financial or account action

**Enforcement mechanism (not just a prompt instruction):** these actions correspond to specific state transitions in `accounts.status` and `cases.status` (`docs/DATABASE_SCHEMA.md`). The API endpoints that perform these transitions require an authenticated human actor with the appropriate RBAC role (`docs/SECURITY.md` §3) and are not reachable by any agent's tool set. There is no code path by which an LLM's output alone triggers one of these transitions. If a future feature seems to require this, it must be raised as an architecture conflict per `CLAUDE.md` §9, not implemented as a shortcut.

---

## 2. Evidence-First Reasoning Chain

Every finding presented to a human must be structurally decomposed as:

```
Observed Fact  →  Derived Signal  →  Interpretation  →  Recommendation
```

- **Observed Fact:** a directly retrievable value from source data (e.g., `transaction_id = TXN-18392, amount = ₹9,80,000`).
- **Derived Signal:** a computed comparison, always reproducible from source data (e.g., "16.3× the customer's 90-day average transfer").
- **Interpretation:** a bounded, non-accusatory characterization (e.g., "significant deviation from historical behavior") — never an accusation or legal conclusion.
- **Recommendation:** always framed as directing a human action (e.g., "recommend human investigator review"), never as a resolution.

This structure is represented in the `findings` table (`observed_fact`, `derived_signal`, `interpretation` columns, `docs/DATABASE_SCHEMA.md` §4.13) — it is a data-model requirement, not merely a prompt template convention, so it can be validated and tested.

**Forbidden report language patterns** (enforced via a wording check in report-generation tests, `docs/TESTING.md`): definitive accusatory phrasing such as "the customer is laundering money," "this is confirmed fraud," "this account should be closed" (without the word "recommend"/"review"). Acceptable: "activity is consistent with patterns associated with elevated AML risk; recommend human investigator review."

---

## 3. Evidence-Sufficiency Gate

Before a `finding` can be included in a generated report:

1. It must have at least one non-empty `evidence_ids` reference (`docs/DATABASE_SCHEMA.md` §4.13), and each reference must resolve to a real row.
2. Its `confidence` must be classified (LOW/MEDIUM/HIGH) using the methodology defined in `docs/EVALUATION.md` — not asserted arbitrarily by the LLM.
3. If evidence is missing, conflicting, of insufficient quality, retrieval confidence is inadequate, a tool call failed, or required information is unavailable, the system must **not** include a confident conclusion for that item. It should instead emit an explicit statement such as `"Insufficient evidence to determine X"` and mark the relevant `investigation_run.status = INCOMPLETE_INSUFFICIENT_EVIDENCE` if this affects the primary finding.

This gate is implemented as an explicit function/service (not left implicit in a prompt) — e.g., `evaluate_evidence_sufficiency(finding) -> bool` — so it is directly unit-testable (`docs/TESTING.md`).

---

## 4. Structured Data vs. RAG Enforcement

Per `CLAUDE.md` §5: any agent code that needs a transactional/customer/account fact must call a structured-query tool, never ask an LLM to recall or estimate it. Code review / tests should flag any agent prompt that asks the LLM to "state" a numeric fact instead of retrieving it, since this is a direct hallucination vector.

---

## 5. Confidence & Uncertainty Labeling

Every numeric/derived output in a report must be labeled with its methodology tier (see `docs/EVALUATION.md`):

| Tier | Meaning | Allowed to drive a HIGH/CRITICAL risk label alone? |
|---|---|---|
| PROTOTYPE | Example/placeholder weights, not validated | No |
| EXPERIMENTALLY_CALIBRATED | Validated against a labeled synthetic set, documented methodology | Contributory, with stated confidence |
| PRODUCTION_APPROVED | Fully evaluated, monitored, versioned (not reached in this project's current phase) | Yes, once actually reached |

MVP risk scoring is PROTOTYPE-tier by design (`docs/FEATURES.md` F10) and must be labeled as such everywhere it's surfaced — in the UI, in the report, and in any documentation or resume/portfolio material. Do not describe prototype scores as "production-grade" or "validated" anywhere.

---

## 6. Failure Handling (AI-Specific)

| Failure | Required behavior |
|---|---|
| LLM unavailable | Queue the investigation step for retry; do not silently skip evidence collection; surface a clear "pending" state to the analyst |
| No relevant policy retrieved | Mark policy evidence as unavailable; report explicitly states no applicable policy was found, rather than omitting the section |
| Conflicting data across agents | Flag for human review; do not have the ReportAgent silently pick one signal over another without surfacing the conflict |
| Low-confidence output | Escalate / label LOW, do not round up to MEDIUM/HIGH for narrative convenience |
| Agent repeatedly fails (defined as: fails validation or throws on retry — retry count **REQUIRES VERIFICATION**/decision at implementation time, default proposal: 2 retries) | Terminate the investigation workflow for that run and notify the analyst; do not present a partial result as if complete |
| Unsupported conclusion detected by the evidence-sufficiency gate | Block report generation for that finding; never suppress the gate to "make the report look complete" |

---

## 7. Testing Obligations Tied to This Document

Per `docs/TESTING.md`, the following are safety-critical and must have explicit automated tests, not just manual/demo verification:
- Evidence-sufficiency gate blocks report generation when evidence is missing.
- Report language checker rejects forbidden accusatory phrasing.
- No code path allows an agent to change `accounts.status` or `cases.status` directly.
- Prompt-injection fixtures do not cause an agent to exceed its tool allow-list or bypass the evidence gate.

---

## 8. Related Documents

`CLAUDE.md` §4 (summary of these same rules for quick reference), `docs/SECURITY.md` (technical enforcement of trust boundaries), `docs/EVALUATION.md` (confidence/methodology tiers), `docs/TESTING.md` (safety-critical test cases), `docs/DATABASE_SCHEMA.md` (`findings`/`evidence` schema backing this gate).
