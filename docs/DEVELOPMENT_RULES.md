# Engineering & Coding Rules — Project Meridian

**Read every coding session?** Yes, always.

---

## 1. General Engineering Principles

Modularity, testability, observability, security, reliability, deterministic behavior where possible, reproducibility, versioning, graceful failure, idempotency, clear module boundaries, least privilege, maintainability. In priority order when trade-offs are necessary: correctness/evidence-integrity → auditability → security → testability → maintainability → performance.

Do not over-engineer. If a simpler design meets the actual requirement, use it. New infrastructure/frameworks require a justification against a demonstrated need, documented per `CLAUDE.md` §9.

---

## 2. Language, Style, and Structure

- **REQUIRES VERIFICATION per session:** exact linter/formatter config (e.g., `ruff`, `black`, `mypy` settings) — read the actual config files in the repo; do not assume defaults.
- Type hints required on all new Python code in this project (FastAPI's typing model depends on it, and it materially reduces hallucination risk in agent/tool code).
- No bare `except:` blocks — catch specific exceptions; log and re-raise or handle explicitly. Silent exception swallowing is a defect, especially in agent tool-call paths where a swallowed error can silently produce an unsupported finding.
- Functions/classes doing DB access, LLM calls, or tool execution must have docstrings stating: inputs, outputs, side effects, and failure modes.

---

## 3. Agent & Tool Code Rules

- Every tool exposed to an agent must have an explicit, narrow input schema (validated, not free-form).
- Tools that execute SQL must use parameterized queries only. **No agent-constructed raw SQL strings, ever** — this is a hard rule tied directly to `docs/SECURITY.md` SQL-injection defenses.
- Every agent invocation must be wrapped so that its `agent_runs` record (per `docs/DATABASE_SCHEMA.md` §4.11) is written even on failure — failures must be observable, not just retried silently.
- LLM calls used for reasoning/synthesis must have their prompt template versioned (a `prompt_version` string) so `docs/OBSERVABILITY_AND_AUDIT.md` records remain meaningful and reproducible.
- Any code that generates a "finding" or "recommendation" must go through the evidence-sufficiency check described in `docs/AI_SAFETY_AND_GUARDRAILS.md` before being persisted as anything other than a draft.

---

## 4. Data Access Rules

- Application code accesses tables only through the module that owns them (`docs/ARCHITECTURE.md` §3). Cross-module reads go through that module's defined interface/service layer, not direct ORM queries into another module's tables.
- No AI-generated write path may modify `customers`, `accounts`, `transactions`, or `beneficiaries` (source data) — these are read-only to the application after import, except through an explicit, audited, human-triggered correction process (`docs/DATABASE_SCHEMA.md` §3).
- Migrations are the only way schema changes happen — no ad hoc `ALTER TABLE` outside a tracked migration file.

---

## 5. Testing Requirements for New Code

No PR/change is complete without corresponding tests appropriate to the change type (see `docs/TESTING.md` for the full taxonomy). At minimum:
- New DB-touching code → integration test against a real (test) PostgreSQL instance, not just mocks.
- New agent/tool → unit test for the tool's input validation and at least one test asserting correct behavior on a known synthetic fixture case (see the worked example in `docs/PRODUCT_BRIEF.md` §5).
- New report-generation logic → test asserting no report is generated when evidence is insufficient (this is a safety-critical path — treat it as such).

---

## 6. Definition of Done

A feature is not "done" merely because code exists and compiles. Per `CLAUDE.md` §10 and `docs/DECISIONS.md`, done means:
- Implementation complete
- Tests written and passing (actually run, not assumed)
- Security review performed where the change touches agent permissions, data access, or external input
- Error handling in place for realistic failure modes
- Observability/audit hooks added where the change affects investigation state
- Documentation (`docs/` + inline docstrings) updated
- No known critical regression

---

## 7. Commit / Change Hygiene

- Commits should be scoped to a single coherent change; avoid bundling unrelated refactors with feature work, since it makes the audit trail and review harder to reason about — which matters more here than in a typical project given Meridian's own auditability mandate.
- Every change that alters agent behavior, schema, or security posture must reference (in the commit message or PR description) the relevant `docs/` file and, if applicable, ADR.

---

## 8. What NOT to Do

- Do not add a new agent "because it would look good" — justify against `docs/ARCHITECTURE.md` §6 criteria first.
- Do not fabricate example outputs, test results, or benchmark numbers in documentation, comments, or commit messages.
- Do not weaken the evidence-sufficiency gate to make demos look more impressive.
- Do not grant an agent's tool broader DB access than its documented responsibility to "save time."
- Do not silently catch and discard exceptions in agent/tool/report-generation code paths.

---

## 9. Related Documents

`CLAUDE.md` (session protocol), `docs/TESTING.md` (full test taxonomy), `docs/SECURITY.md` (security review checklist), `docs/AI_SAFETY_AND_GUARDRAILS.md` (evidence-sufficiency gate detail).
