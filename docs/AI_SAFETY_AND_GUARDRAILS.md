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
| F11 sanctions screening failure or controlled abstention | Non-fatal to overall investigation workflow (see §6.1); mandatory disclosure of persisted state or "Not determined" in report; never treated as clearance |

### 6.1 F11-Specific Safety Exception (Sanctions/Watchlist Screening)

F11 is a supplementary screening signal designed as an additive candidate-generation step. To legitimately satisfy ADR-0008, the following narrow, deliberate, and bounded exception applies exclusively to F11 when it is operationally wired (Task 24):

- **Successful F11 Outcomes (CANDIDATE_MATCHES_FOUND, NO_CANDIDATE_MATCH):** Normal operation; these do not terminate the investigation workflow.
- **Controlled F11 Abstention (`NOT_PERFORMED`):** Occurs when screening cannot be performed due to known conditions (e.g., customer name unavailable, customer name normalizes to empty, configured/pinned watchlist unavailable). This is a SUCCESS outcome conceptually distinct from technical failure. Its explicit screening outcome is `NOT_PERFORMED`. This state must be explicitly disclosed to the human investigator and must never be presented as a `NO_CANDIDATE_MATCH` or clearance.
- **Technical F11 Failure:** A runtime failure (e.g., database failure, watchlist integrity failure, normalization-version mismatch, unexpected matcher exception, or agent-run failure). Unlike primary agents, an F11 technical failure does not by itself terminate the overall investigation workflow. This exception is granted *provided* that the resulting unavailable/failed screening state is explicitly disclosed to the human investigator and is never represented as a successful no-match, clearance, or completed screening.

This exception governs only the investigation-level consequence of an F11 failure; it does not change the unresolved retry-count policy in §6 or the §3 sufficiency gate. This is not a general supplementary-agent policy. Any other agent failure continues to terminate the investigation per the general rule.

#### 6.1.1 Contract Specification and Outcome Categories (ADR-0008 D7–D10)

This exception applies **ONLY** to the F11 sanctions/watchlist screening step (`SanctionsAgent`). All other agents—including `TransactionAgent`, `PolicyAgent`, `GraphAgent`, and `ReportAgent`—remain strictly governed by existing failure-handling and termination rules. This exception is not a general supplementary-agent policy and must not be generalized to other agents or tool failures.

Per ADR-0008 D7–D8, the four distinct F11 outcome categories are defined as follows:

1. **Candidate found:**
   - Screening agent run execution status is `SUCCESS`.
   - Persisted domain outcome in `screening_results` is `CANDIDATE_MATCHES_FOUND` with `candidate_count > 0` and `reason_code = NULL`.
   - A candidate is a subject requiring human review, not an identity or sanctions determination.
2. **No candidate:**
   - Screening agent run execution status is `SUCCESS`.
   - Persisted domain outcome in `screening_results` is `NO_CANDIDATE_MATCH` with `candidate_count = 0` and `reason_code = NULL`.
   - This outcome is not clearance.
3. **Controlled abstention:**
   - Screening agent run execution status is `SUCCESS` (the agent ran successfully and correctly determined that screening could not proceed).
   - Persisted domain outcome in `screening_results` is `NOT_PERFORMED` with `candidate_count = 0` and an approved `reason_code` (`CUSTOMER_NAME_MISSING`, `CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION`, or `WATCHLIST_VERSION_NOT_LOADED`).
   - Controlled abstention does not make the overall investigation fatal or incomplete by itself.
4. **Technical or integrity failure:**
   - Screening agent run execution status is `FAILED` (with an approved technical error code recorded in `agent_runs.error`: `WATCHLIST_INTEGRITY_VIOLATION`, `NORMALIZATION_VERSION_MISMATCH`, `DATABASE_ERROR`, or `UNEXPECTED_ERROR`).
   - No row is written to `screening_results` for that failed attempt.
   - The failure is disclosed in the report as "Not determined," accompanied by the applicable reason where available.
   - Technical or integrity failure does not make the overall investigation fatal or incomplete by itself.

#### 6.1.2 Preservation of Investigation Completion Prerequisites

The F11 exception does not bypass, weaken, or replace any existing investigation-completion prerequisite. It only prevents F11 abstention or failure from independently making the investigation fatal or incomplete.

The existing transaction and policy evidence rules continue to determine investigation completion: marking an investigation `COMPLETE` strictly requires satisfactory primary transaction and policy evidence. Under no circumstances may an investigation be marked `COMPLETE` when its primary evidence prerequisites are unsatisfied.

#### 6.1.3 Report Disclosure and Inconsistency Handling

Every investigation report must contain a watchlist screening section displaying the persisted F11 state. Abstention, technical failure, screening persistence failure, inconsistent screening records, and unrecorded screening must not be silently omitted; each must be explicitly disclosed as "Not determined," along with the applicable reason or inconsistency state.

The report must never manufacture or infer a persisted F11 domain outcome from `agent_runs.status`, candidate evidence, findings, or generated report text. The domain outcome must come from the persisted `screening_results` record when present and consistent with the ADR-0008 contract.

When the screening result row is absent, the associated `SanctionsAgent` run's presence, identity, and status may be used only to classify the report state according to the seven-state contract below. This classification does not create a screening outcome. When a result row exists but fails the contract's consistency checks, the report must use the existing inconsistent-screening-record state rather than trusting the row's domain outcome. Per ADR-0008 D10, the watchlist screening section is rendered according to the following seven-state contract:

| Persisted state | Rendered as |
|---|---|
| Row `CANDIDATE_MATCHES_FOUND`, consistent | Candidates, with list name, version and rule |
| Row `NO_CANDIDATE_MATCH` | "No candidate match against synthetic list X vN. This is not a clearance." |
| Row `NOT_PERFORMED` | "Not determined", with the reason |
| No row; a `SanctionsAgent` run for the same `investigation_run_id` with status FAILED | "Screening error. Not determined." |
| No row; a `SanctionsAgent` run for the same `investigation_run_id` with status SUCCESS (or PARTIAL) | "Inconsistent screening record. Not determined." |
| No row; no `SanctionsAgent` run for the same `investigation_run_id` | "Screening not recorded. Not determined." |
| Row exists but the referenced run is not a SUCCESS `SanctionsAgent` run of the same investigation run, or `candidate_count` does not equal the candidate finding count | "Inconsistent screening record. Not determined." |

#### 6.1.4 Human Review and Prohibited Interpretations

Human review remains strictly required for all screening outcomes:
- Controlled abstention is not clearance.
- Technical failure is not clearance.
- Screening persistence failure is not clearance.
- An unrecorded or inconsistent result is not clearance.
- `NO_CANDIDATE_MATCH` is not clearance.
- A candidate match is not a confirmed identity or sanctions determination.

No F11 outcome, candidate match, or absence of a candidate match may independently trigger or imply an account action, regulatory filing, or final suspicious-activity determination.

Per ADR-0008 D10, wording prohibited in Meridian-authored text comprises: `"sanctioned customer"`, `"confirmed hit"`, `"criminal"`, `"money laundering"`, `"cleared"`, `"clean"`, and `"no sanctions exposure"`. All candidate matches must explicitly state that the match is a candidate for human review and not an identity or sanctions determination.

#### 6.1.5 Implementation Status and Testing Obligations

- **ADR Status:** ADR-0008 status is **Accepted** (dated 2026-10-08, accepted 2026-10-09 per `docs/DECISIONS.md` and commit `a92c4b566369060ee4ac879864b748a2294c05bf`).
- **Implementation State:** The F11 exception is defined in ADR-0008 D9. The corresponding runtime orchestrator wiring, two-stage persistence, authoring, audit-trail integration, and report rendering behaviors are implemented in the application across Task 24 Stages 2a and 2b (`src/meridian/orchestration/investigation_orchestrator.py`, `src/meridian/orchestration/screening_results_persistence.py`, `src/meridian/agents/report/screening_classification.py`, `src/meridian/agents/report/report_assembly.py`, `src/meridian/audit/audit_trail.py`).
- **Historical Sequencing Note:** ADR-0008 D9 specified that Section 6 of this document be updated prior to implementing SanctionsAgent wiring. While high-level exception text was committed in 4b8b949, detailed contract subsections §6.1.1–§6.1.5 remained uncommitted in the working tree while implementation commits landed; strict D9 sequencing compliance is therefore historically UNVERIFIED in repository history.
- **Testing Obligations:** Automated F11 AI-safety tests enforcing non-fatality, explicit disclosure of unrecorded/failed states, and prohibition of clearance claims are implemented in `tests/test_sanctions_orchestration_wiring.py` and `tests/test_watchlist_screening_rendering.py`.

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
