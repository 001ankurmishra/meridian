# Product, UX, Technical & Interaction Design — Project Meridian

**Read every coding session?** Conditionally — yes for any frontend/UX work or report-generation formatting.

---

## 1. Design Intent

Meridian should feel like an **investigation workspace**, not a chatbot. An analyst opens a case and sees a structured, evidence-organized view of everything relevant — not a conversation thread they have to interrogate. Chat-style interaction (if present at all) is a secondary, optional layer for ad hoc questions, not the primary interface.

---

## 2. Core Workspace Layout

A case view surfaces, per the brief's UX goals (organized here into a concrete layout):

**Header band:** Alert summary, case ID, risk level badge (LOW/MEDIUM/HIGH/CRITICAL), status, assigned analyst.

**Left panel — Context:**
1. Customer profile (KYC info, tenure, risk rating)
2. Alert detail (why it fired)

**Center panel — Evidence & Analysis (tabbed):**
3. Transaction anomaly view (the alerted transaction + historical comparison chart)
4. Behavioral history (trend of the customer's typical activity vs. current)
5. Related entities list
6. Transaction graph (interactive node/edge view — see §4)
7. Risk signals (itemized, each linked to contributing evidence)
8. Supporting evidence (list of evidence records, each clickable to source)
9. Relevant policy (retrieved policy excerpts with citation + document version)

**Right panel — Reasoning & Action:**
10. Investigation timeline (chronological agent-run log)
11. AI reasoning summary (Fact → Signal → Interpretation → Recommendation chain, rendered explicitly — not collapsed into unstructured prose)
12. Confidence & limitations (explicit — what evidence is missing or low-confidence)
13. Recommended next actions
14. Human decision controls (Approve / Reject / Request More Info / Escalate — see §5)
15. Full audit trail (expandable, links to `audit_events`)

This maps directly to `PROJECT_BRIEF` §17's 15-point list; nothing was dropped, but it is organized into a coherent three-panel layout rather than a flat list, and reasoning/uncertainty are surfaced as prominently as the recommendation itself (per Product Principle 1).

---

## 3. Uncertainty Must Be Visible, Not Hidden

This is a hard design requirement, not a nice-to-have:

- Any finding with `confidence = LOW` is visually distinguished (not just color — also a text label, for accessibility) from HIGH-confidence findings.
- If an agent returned `UNKNOWN` for a signal, the UI shows "Not determined" explicitly rather than omitting the row silently — an analyst should be able to see *what the system tried and couldn't establish*, not just what it found.
- The overall report never presents a risk level without also surfacing the evidence-completeness state of the investigation (`COMPLETE` vs `INCOMPLETE_INSUFFICIENT_EVIDENCE`, per `investigation_runs.status`).
- No dashboard element implies more precision than the underlying score supports (e.g., don't render a risk score as "87.3/100" if the scoring methodology is PROTOTYPE-tier — see `docs/EVALUATION.md`).

---

## 4. Transaction Graph View

- Interactive node/edge graph (nodes: customers/accounts/beneficiaries/devices; edges: transfers/relationships), built from `graph_relationships`.
- Edge weight/thickness reflects transaction amount or frequency; node color reflects entity risk signal, not raw AI confidence (avoid conflating "this account looks risky" with "the AI is confident").
- Clicking a node/edge opens the underlying evidence (source transactions).
- Depth-limited by default (matches `GraphAgent`'s bounded hop-depth, `docs/ARCHITECTURE.md` §4.3); a "expand further" control is explicit rather than the graph silently growing unbounded.

---

## 5. Human Decision Controls

Four explicit actions, each requiring the acting analyst's identity to be recorded (`docs/OBSERVABILITY_AND_AUDIT.md`):

| Action | Effect | Who can perform |
|---|---|---|
| Approve | Marks case `CLOSED_APPROVED`; recommendation accepted | Assigned analyst or senior analyst |
| Reject | Marks case `CLOSED_REJECTED`; recommendation rejected with required reason text | Assigned analyst or senior analyst |
| Request More Info | Reopens/extends `investigation_run`; can specify what's missing | Assigned analyst |
| Escalate | Marks case `ESCALATED`; routes to compliance manager | Assigned analyst or senior analyst |

None of these controls exist for the AI itself to invoke — they are human-only UI actions gated by RBAC (`docs/SECURITY.md`).

---

## 6. Report Formatting

The generated investigation report (rendered in-app and exportable) follows a fixed structure so it stays scannable and auditable:

```
AML INVESTIGATION REPORT
Case ID / Customer (synthetic) / Risk Level / Evidence-Completeness Status

Summary (2–4 sentences, no unsupported claims)

Key Findings (numbered; each with Fact → Signal → Interpretation)
Evidence (itemized, linked to source records)
Applicable Policy (citation + version)
Recommendation
Confidence (with stated basis, not just a word)
Human Review Required: YES (always, structurally — never omitted)
```

This mirrors the worked example in `docs/PRODUCT_BRIEF.md` §5.

---

## 7. Accessibility & Tone

- Color is never the sole indicator of risk level or confidence — always paired with text/labels.
- Language in the report avoids accusatory framing ("the customer is laundering money") in favor of evidence-framed language ("activity deviates significantly from historical pattern; recommend review") — this is a wording rule enforced in `docs/AI_SAFETY_AND_GUARDRAILS.md` and checked by tests in `docs/TESTING.md`.

---

## 8. MVP UI Scope

Per `docs/ROADMAP.md`, the MVP frontend may be a simpler Streamlit implementation covering panels 1–2, 3, 7–9, 11–14 (core investigation + evidence + decision), with the full graph view (panel 6) and timeline/audit expansion (10, 15) following in the React-based Phase 2 build. This phased scope is a **PROPOSAL** — confirm against actual sprint capacity when Phase 1 begins.

---

## 9. Related Documents

`docs/FEATURES.md` (feature-level detail behind each panel), `docs/ARCHITECTURE.md` (data backing each view), `docs/AI_SAFETY_AND_GUARDRAILS.md` (report-language constraints).
