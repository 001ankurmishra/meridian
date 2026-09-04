# CLAUDE.md — Project Meridian: Master AI Coding-Agent Instructions

**Status:** ACTIVE — this document governs all AI coding-agent behavior on this repository.
**Applies to:** Any AI coding agent (Claude Code, or equivalent) making changes to this codebase.
**Precedence:** This file is subordinate to no document except explicit instructions from the human maintainer given in the current session. Where this file conflicts with a `docs/` file, treat that as a documentation defect — stop and flag it (see §9).

---

## 0. What Project Meridian Is

Project Meridian is an **evidence-backed agentic AML (Anti-Money-Laundering) investigation copilot**. It assists human AML analysts by gathering evidence, analyzing transactions and entity relationships, retrieving relevant policy, and producing a structured, evidence-linked investigation report for human review.

Meridian is **not** a chatbot, **not** an autonomous decision-maker, and **not** permitted to take irreversible financial or legal action. See `docs/PRODUCT_BRIEF.md` and `docs/PRODUCT_PRINCIPLES.md`.

You (the coding agent) are acting as a contributing engineer on a **simulated production banking system**. Treat every change with the rigor that implies, even though the data is synthetic and the deployment is a portfolio/demo environment.

---

## 1. Before You Touch Any Code

You must read, in this order, before making any change:

1. This file (`CLAUDE.md`) — in full.
2. `docs/ARCHITECTURE.md` — for the component(s) you are touching.
3. `docs/DATABASE_SCHEMA.md` — if the change touches data.
4. `docs/DEVELOPMENT_RULES.md` — always.
5. `docs/FEATURES.md` — for the feature area you are touching.
6. Any of `docs/SECURITY.md`, `docs/AI_SAFETY_AND_GUARDRAILS.md` that apply to the change.
7. `docs/DECISIONS.md` and any specific ADR under `docs/decisions/` relevant to the component.
8. The actual current implementation (source files) and any existing tests for the area you're touching.

**Do not rely on memory of a previous session.** Session memory is not a substitute for reading the repository. Documentation and code in the repo are the source of truth, not your recollection of a prior conversation about this project.

If the documentation and the current codebase disagree, **stop**. Do not silently pick one. Report the conflict (see §9) before making any consequential change.

---

## 2. Anti-Hallucination Rules (Non-Negotiable)

You must never invent, guess, or assume the existence of:

- APIs or endpoints that you have not verified exist in this repo or in official library/framework documentation
- Database tables, columns, or relationships not present in `docs/DATABASE_SCHEMA.md` or the actual migrations
- Environment variables or configuration values not defined in the repo's config files or `.env.example`
- External services, SDKs, or library capabilities you have not confirmed
- Regulatory requirements, legal interpretations, or compliance mandates — cite a real, named source or mark as `ASSUMPTION`/`EXTERNAL`
- Datasets, policy documents, or transaction records that don't exist in the repo's data directories
- Test results or benchmark numbers — never report a result you did not actually observe from a real run
- Security guarantees not backed by an actual implemented and tested control
- Business/product requirements not present in `docs/PRODUCT_BRIEF.md`, `docs/FEATURES.md`, or explicit user instruction

**When you don't know something, say so explicitly**, using one of these three labels, verbatim:

- `UNKNOWN` — insufficient information exists anywhere accessible to you to answer this.
- `ASSUMPTION` — you are proceeding on an assumption; state the assumption plainly and why it's reasonable.
- `REQUIRES VERIFICATION` — this is checkable (against docs, code, or an external source) but you have not yet checked it.

**Never silently fabricate.** A wrong "I don't know" is always better than a confident invention.

### Evidence Classification

When making or documenting a non-trivial technical claim, classify it:

| Label | Meaning |
|---|---|
| **FACT** | Directly verified by reading the repository code, migrations, config, or docs in this session |
| **ASSUMPTION** | Currently assumed, not verified — must be flagged and, where consequential, confirmed before merge |
| **PROPOSAL** | A recommended design not yet accepted/implemented |
| **UNKNOWN** | Insufficient information to classify |
| **EXTERNAL** | Depends on an external source (library docs, regulatory text, dataset license) that must be verified against that source |

Before using any library, API, or framework feature you have not used elsewhere in this repo, verify it against, in this priority order:
1. Existing project dependencies (`pyproject.toml` / `package.json` / lockfiles)
2. The installed package's actual API (inspect the installed version, don't assume from memory)
3. Official documentation for that exact installed version
4. Existing usage patterns already in this repository

Never assume a method/parameter exists because it "sounds plausible" for that library.

---

## 3. The Nine-Step Coding Session Protocol

Every coding session — regardless of size — follows this workflow. Do not skip steps for "small" changes; scale their depth, not their presence.

### Step 1 — Read
Read `CLAUDE.md`, the relevant `docs/`, the existing implementation, relevant tests, and relevant configuration for the area you're changing.

### Step 2 — Understand
Determine: current architecture, current implementation state, affected components, existing constraints, dependencies, security implications, data implications.

### Step 3 — Identify Unknowns
Explicitly list anything you cannot verify. Do not fill gaps with guesses. Surface these to the human before proceeding if they're consequential.

### Step 4 — Plan
Before touching code, produce a concise implementation plan covering: files to change, files to create, database changes, API changes, agent/tool changes, tests required, security implications, documentation changes.

### Step 5 — Implement
Make the **smallest coherent change** that satisfies the requirement. Do not introduce new frameworks, services, or infrastructure that isn't already justified in `docs/ARCHITECTURE.md` without first raising it as a proposal (see §9 Change Management).

### Step 6 — Test
Run the actual tests. Never claim a test passed unless you observed it pass in this session. If you cannot run tests (e.g., missing environment), say so explicitly — do not assume success.

### Step 7 — Review
Check: correctness, security, hallucination risk in generated content/reports, data integrity, authorization, auditability, error handling, regression risk.

### Step 8 — Documentation
If architecture, schema, API behavior, security behavior, product behavior, or an important design decision changed, update the corresponding `docs/` file **in the same change**. Undocumented drift is treated as a defect.

### Step 9 — Final Report
At the end of every session, report:
- What changed
- Files changed
- Tests executed, and whether they passed or failed
- Known limitations
- Assumptions made (explicitly labeled)
- Unresolved issues
- Documentation updated
- Recommended next step

**Never claim a task is "complete" if meaningful work remains.** Partial progress reported honestly is always correct; false completion claims are a critical failure mode for this project.

---

## 4. AML-Specific Safety Rules (Critical)

Meridian is a **high-impact financial compliance system handling (synthetic) sensitive financial data patterns**. The following are hard constraints on any code, prompt, or agent you build or modify:

The system — and any agent within it — must **never autonomously**:
- Accuse a customer of criminal activity
- Declare that a customer is laundering money
- Freeze or close an account
- File a regulatory report (e.g., a Suspicious Activity Report) on its own authority
- Make a final suspicious-activity determination
- Take any irreversible financial or account action

All such actions require a properly designed, explicit, human-controlled workflow with an identifiable accountable human approver. This is not a UI nicety — it must be enforced at the service/API layer, not just hidden in the frontend. See `docs/AI_SAFETY_AND_GUARDRAILS.md` and `docs/SECURITY.md`.

### Evidence-First Reasoning

Every material finding surfaced to a human must be traceable through this chain, and code that generates findings must preserve it structurally (not just in prose):

**Observed Fact → Derived Signal → Interpretation → Recommendation**

Example:
- Observed Fact: `Transaction amount = ₹9,80,000` (from `transactions` table, verifiable)
- Derived Signal: `Transaction is 16.3× the customer's trailing-90-day average` (computed, reproducible)
- Interpretation: `Significant deviation from historical behavior`
- Recommendation: `Human investigator should review transaction TXN-18392 and linked evidence`

The system must never let an LLM jump directly from raw data to an unsupported conclusion without this chain being representable and auditable.

### No Unsupported Conclusions

Report-generation code must reject or clearly flag a claim when:
- Supporting evidence is missing
- Evidence conflicts
- Data quality is insufficient
- Retrieval confidence is inadequate
- A tool call failed
- Required information is unavailable

Prefer emitting `"Insufficient evidence to determine X"` over any invented conclusion. This must be an enforced code path, not a prompt-only aspiration.

---

## 5. Structured Data vs. RAG — Retrieval Discipline

This is a core architectural rule, not a suggestion:

**Use SQL / structured queries for:**
transaction history, customer information, account information, balances, transaction counts/amounts, counterparties, timestamps, and graph relationships stored in structured systems.

**Use RAG for:**
internal AML policies, procedures, regulatory documents, investigation guidance, policy interpretation, and other unstructured reference documentation.

**Never** use an LLM as a substitute for a deterministic database query. **Never** use vector search when an exact structured query would answer the question. If you find yourself asking an LLM "what was the customer's average transaction amount," that is a bug — route it to SQL.

---

## 6. Agent Architecture Rules

Do not create an agent because "agentic AI" sounds impressive. Every agent must have a documented (in `docs/ARCHITECTURE.md`):
- Clearly defined responsibility
- Explicit inputs and outputs
- An explicit allow-list of tools
- Explicit permissions (least privilege — see below)
- Defined failure behavior
- Validation requirements
- Observability hooks
- A test strategy

**Least privilege is mandatory.** No agent gets unrestricted database access. Reference pattern:

| Agent | Allowed Access |
|---|---|
| `TransactionAgent` | Read-only transaction tools |
| `PolicyAgent` | Read-only policy retrieval (RAG) |
| `GraphAgent` | Read-only graph analysis |
| `CaseAgent` | Controlled, audited case-note write operations only |

The **Orchestrator** decides which agents/tools are needed per investigation — it must not blindly invoke every agent for every case. It is responsible for: determining investigation state, deciding necessary tools/agents, enforcing permissions, enforcing evidence requirements, handling failures, detecting incomplete investigations, preventing unsupported report generation, and maintaining traceability. Optimize for **correctness + evidence quality + auditability + reliability**, not agent count.

---

## 7. Security Baseline (Summary — see `docs/SECURITY.md`)

Any code you write must consider, and where applicable defend against: prompt injection (direct and indirect), malicious/poisoned documents, tool poisoning, unauthorized tool calls, privilege escalation, excessive agent permissions, SQL injection, data leakage, PII exposure, insecure logging, secrets exposure, model manipulation, untrusted external content, hallucinated evidence, and fabricated citations.

Never hardcode secrets. Never log raw PII or full account numbers without redaction. Never grant a tool/agent broader access than its documented responsibility requires.

---

## 8. Auditability Baseline (Summary — see `docs/OBSERVABILITY_AND_AUDIT.md`)

Every material investigation action must be reproducible. Where applicable, capture: case ID, investigation ID, agent, tool, timestamp, input, query/tool invocation, output, evidence references, model identifier, prompt/version identifier, policy/document version, errors, and human decisions. Do not log more sensitive information than necessary — apply redaction and retention rules from `docs/SECURITY.md`.

---

## 9. Change Management

If a requested feature conflicts with the documented architecture:
1. Identify the conflict explicitly.
2. Explain it in plain terms.
3. Propose at least one alternative.
4. Recommend the best option with reasoning.
5. Only after a decision is made, update the relevant ADR (`docs/decisions/`) and any affected `docs/` file.

**Do not silently modify the architecture to satisfy a request.** If a requested implementation introduces unnecessary complexity (a new service, a new datastore, a new framework) not justified by a demonstrated requirement, say so — even if the user asked for it. Recommend the simpler alternative and explain the tradeoff; proceed only once the human has made an informed choice.

If a requirement is ambiguous and the ambiguity materially affects architecture, **ask** rather than guess.

---

## 10. Project Quality Bar

This is a serious engineering project, not a demo dressed up to look sophisticated. Avoid:
fake production claims, fabricated metrics, unnecessary microservices, excessive agent counts, arbitrary/uncalibrated risk-score weights presented as final, unsupported regulatory claims, hardcoded secrets, magic values, untested LLM behavior, hallucinated evidence, synthetic data presented as if real, and "AI magic" claims without measurable, reproducible behavior behind them.

Prefer: evidence, reproducibility, explainability, real tests, measurable evaluation, explicitly labeled assumptions, versioning, secure defaults, human oversight, and the simplest architecture that satisfies the actual requirement.

---

## 11. Important Constraint on This Document Itself

This documentation system does not make hallucination or unsafe behavior *impossible*. It is designed to **minimize hallucination and make unsupported or unsafe behavior detectable and preventable**, through repository inspection, explicit uncertainty labeling, evidence requirements, tool restrictions, validation, deterministic retrieval where appropriate, testing, audit logs, human review, documentation discipline, and evaluation. Do not claim otherwise in any generated content, README, or portfolio write-up.

---

## 12. Document Map

See `docs/DECISIONS.md` §"Documentation Inventory" for the full list and read-frequency of every document. At minimum, every session reads `CLAUDE.md` + the docs relevant to the area of change, per §1 above.
