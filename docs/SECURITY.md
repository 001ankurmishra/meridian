# Security & AI Safety Requirements — Project Meridian

**Read every coding session?** Yes, for any change touching auth, data access, agent tools, or external input.

---

## 1. Trust Boundaries

```
[Untrusted] External alert sources, uploaded/ingested documents, any LLM-generated text
     │
     ▼
[Boundary: input validation + schema enforcement]
     │
     ▼
[Semi-trusted] Agent reasoning/output (LLM-generated — never trusted for direct action)
     │
     ▼
[Boundary: tool permission layer — least privilege, parameterized access only]
     │
     ▼
[Trusted] Structured data layer (PostgreSQL), audit log
     │
     ▼
[Boundary: human authorization gate]
     │
     ▼
[Authoritative] Case disposition, account status, any irreversible action
```

Key rule: **LLM output is never trusted as an authorization signal.** An agent recommending "escalate" does not escalate anything by itself — only a human action through the `review` module (`docs/DESIGN.md` §5) changes case disposition.

---

## 2. Threats & Controls

| Threat | Control |
|---|---|
| **Prompt injection (direct)** | User-supplied text passed to an LLM is never treated as an instruction to change tool permissions or bypass evidence checks; system prompts are structurally separated from user/data content; agents validate tool-call arguments against a strict schema regardless of what the LLM "asked for." |
| **Indirect prompt injection** | Retrieved documents (policy chunks, ingested case notes) are treated as data, not instructions. RAG-retrieved content is never concatenated into a system-level prompt position; agent code must not execute instructions found inside retrieved text (e.g., "ignore previous instructions" embedded in a document must have no effect). |
| **Malicious/poisoned documents** | Ingested documents (for RAG) go through a defined ingestion pipeline with content-type validation; the ingestion process itself doesn't execute document content. Document provenance (`documents.source_url_or_ref`, `is_synthetic`) is tracked so a poisoned/untrusted source is identifiable. |
| **Tool poisoning** | Tool definitions are fixed in code, not dynamically generated from untrusted input; no agent can register a new tool at runtime from LLM output. |
| **Unauthorized tool calls** | Each agent has a hard-coded allow-list of tools (`docs/ARCHITECTURE.md` §4); tool-call requests outside that list are rejected before execution, not just discouraged via prompt. |
| **Privilege escalation** | No agent tool can grant itself or another agent broader access; permission checks happen at the tool-execution layer, independent of what the LLM requests. |
| **Excessive agent permissions** | Least-privilege table (`docs/ARCHITECTURE.md` §4) is the authoritative permission spec; new tools default to read-only unless a write is explicitly justified and reviewed. |
| **SQL injection** | All SQL is parameterized; no agent or user input is ever interpolated into a raw SQL string. Agent "SQL tools" expose a constrained query builder / fixed parameterized query set, not free-text SQL execution (`docs/DEVELOPMENT_RULES.md` §3). |
| **Data leakage / PII exposure** | Redaction applied before any data is included in logs (`audit_events.input_summary`/`output_summary`), LLM prompts include only the minimum fields needed for the task, and full account numbers/DOBs are masked in any output surface not specifically designed to show them to an authorized human. |
| **Insecure logging** | No secrets, credentials, or unredacted PII in logs; structured logging with redaction applied at the logging boundary, not left to each call site's discretion. |
| **Secrets exposure** | No secrets in source control; environment-variable-based config with a documented `.env.example`; automated Gitleaks secret scanning in CI and local verification. |
| **Model manipulation** | Model/provider selection is abstracted (`docs/ARCHITECTURE.md` §6); output from the model is validated against expected schema before being used downstream (e.g., a "finding" object must match a defined structure — reject and flag if it doesn't). |
| **Untrusted external content** | Any externally sourced content (documents, alert payloads) is validated and provenance-tagged before entering the evidence pipeline. |
| **Hallucinated evidence / fabricated citations** | Evidence records must reference real rows in the database (application validation of source pointers and same-run finding/evidence links, rechecked at report assembly); a citation with no resolvable source record is a hard validation failure, not a warning. |

---

## 3. Authorization Model

RBAC roles (`docs/DATABASE_SCHEMA.md` §4.18):

| Role | Can view cases | Can Approve/Reject | Can Escalate | Admin functions |
|---|---|---|---|---|
| `analyst` | Assigned cases | Yes (own cases) | Yes | No |
| `senior_analyst` | All cases | Yes | Yes | No |
| `compliance_manager` | All cases, incl. escalated | Yes | — (receives escalations) | Limited (policy doc management) |
| `admin` | All | No (separation of duties — admins configure, don't adjudicate) | No | Yes |

Enforced server-side on every case-mutating endpoint; the UI hiding a control is not a substitute for server-side enforcement.

**Implementation status:** Task 20 (ADR-0007) implemented a DEMO grade authentication model using opaque bearer tokens (server-side SHA-256 hash storage in `api_tokens`). The acting user is derived from the validated token on all protected case routes (`POST /cases`, `POST /cases/{id}/investigate`, `GET /cases/{id}/report`, `POST /cases/{id}/decision`, `GET /cases/{id}/audit-trail`, and `GET /cases/{case_id}/investigations/{run_id}/copilot-draft`). Case visibility rules (e.g., 404 Not Found for unassigned analysts) are enforced server-side.

**Explicit Limitations:** This is not production IAM. There is no automated rate limiting, no account lockout, no refresh token rotation, and no TLS applied locally. The `/health` endpoint remains unauthenticated and uses only the application database role.


Phase B identity controls:
- Runtime uses only `APP_DATABASE_URL`; it has SELECT-only access to `users` and
  `api_tokens`. `DATABASE_URL` is migration-only; API startup does not require it.
- Provision/revoke/deactivate with `PYTHONPATH=src uv run --frozen --no-sync python
  -m meridian.identity.cli` using an explicitly exported `MAINTENANCE_DATABASE_URL`.
  Subcommands: `issue EMAIL --ttl HOURS`, `revoke TOKEN_ID`, `revoke-all EMAIL`,
  `deactivate EMAIL`. Supply privileged credentials through the local environment,
  never chat, source code or a runtime container. Issuance displays the bearer
  secret once; use a private terminal. Maximum TTL is 168 hours.
- Issuance, revocation and deactivation record atomic audit events without token
  secrets, hashes, labels or email addresses. The authenticated maintenance actor
  is the database session principal; this does not identify an individual human
  sharing that database credential.
- `users.is_active` defaults true for existing identities. Deactivation atomically
  revokes tokens, rejects subsequent issuance and denies verification. Issuance
  serializes against deactivation on the user row. No self-service reactivation
  or new assignment workflow is introduced; ADR-0007's assignment deferral stays.
- Case and decision bodies reject extra fields, including supplied actor identity.
  Human decisions retain their existing RBAC and atomic case-update/audit behavior.

---

## 4. Data Retention & Redaction

- Synthetic PII fields (name, DOB) are retained as needed for the demo/portfolio dataset but are always `is_synthetic = true` (`docs/DATABASE_SCHEMA.md` §4.1) and never presented as real.
- Audit log input/output summaries store redacted representations (e.g., last 4 digits of an account reference) sufficient for reconstructing *what happened* without storing full sensitive values redundantly.
- Retention periods for audit logs and case data: **ASSUMPTION** — indefinite retention for this portfolio project (no regulatory retention-period requirement applies to synthetic data), revisit if the project is ever extended toward real data handling.

---

## 5. Prompt-Injection Defense — Concrete Pattern

```
System prompt (fixed, code-defined)
  + Task instructions (fixed, code-defined)
  + [DATA BLOCK — clearly delimited] retrieved policy chunk / case note / alert text
  + Structured output schema requirement
```

Agent code must:
1. Never let the DATA BLOCK content be interpreted as new instructions (enforce via prompt structure and, ideally, provider-level system/user role separation).
2. Validate the LLM's structured output against a schema before use.
3. Log the exact prompt version and retrieved chunk IDs used, so a successful injection attempt (if one occurred) is forensically traceable.

Testing requirement: `docs/TESTING.md` requires adversarial test cases with injected instructions embedded in synthetic documents/case notes, asserting the agent does not deviate from its allowed tool set or evidence rules.

---

## 6. Secret Scanning Controls (Phase 3)

Automated secret scanning prevents credentials, API keys, private keys, and tokens from entering the repository history.

- **Tooling & Pinning:** Gitleaks CLI for local scanning and the official GitHub Action pinned to an immutable commit SHA (`gitleaks/gitleaks-action@e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e` # v3.0.0) with an immutably pinned checkout action (`actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803` # v6.1.0) and explicit least-privilege token permissions (`permissions: contents: read`) in `.github/workflows/ci.yml`. Automated PR comments are explicitly disabled (`GITLEAKS_ENABLE_COMMENTS: "false"`), eliminating any need for write permissions.
- **Scanner Version Parity:** Scanner version `8.30.1` is explicitly pinned in CI via `GITLEAKS_VERSION: "8.30.1"`, matching the local developer baseline. Developers can verify local CLI parity using:
  ```bash
  gitleaks version
  ```
- **CI Integration:** Dedicated `secret-scan` job running across full commit history (`fetch-depth: 0`) on every pull request and push.
- **Recommended Local Commands:**
  - **Pre-commit / staged check (canonical developer workflow):**
    ```bash
    gitleaks git --pre-commit --staged --verbose --redact
    ```
  - **Unstaged working tree check (tracked files):**
    ```bash
    gitleaks git --pre-commit --verbose --redact .
    ```
  - **Full repository history scan:**
    ```bash
    gitleaks git --verbose --redact .
    ```
  - **Single commit scan (current HEAD):**
    ```bash
    gitleaks git --log-opts="-1 HEAD" --verbose --redact .
    ```
  - **Targeted directory scan (filesystem):**
    ```bash
    gitleaks dir --redact src/    # or tests/, docs/
    ```
- **Distinction Between Scanning Modes:**
  - *Staged scan (`gitleaks git --pre-commit --staged`):* Git-aware; inspects only files and modifications staged in the Git index for the next commit. Bypasses untracked files and `.gitignore` entries. Recommended before every commit.
  - *Historical scan (`gitleaks git`):* Git-aware; traverses all committed blobs across the repository's commit history graph. Used in CI (`fetch-depth: 0`) and repository audits. Does not inspect uncommitted working tree changes.
  - *Directory scan (`gitleaks dir`):* Filesystem-aware, non-Git; recursively walks raw disk files. Does not read `.gitignore` or Git tracking state. Running against root (`.`) will traverse local caches, virtual environments (`.venv/`), and scratch files; filesystem scanning must therefore target specific project subdirectories (`src/`, `tests/`, `docs/`).
- **False-Positive Handling & Allowlist Policy:**
  - Broad directory, file, or rule exclusions (such as blanket ignores for `tests/`, `docs/`, or fixtures) are strictly prohibited.
  - Base configuration resides in `.gitleaks.toml` (`[extend] useDefault = true`).
  - Known benign matches are audited individually and recorded by exact fingerprint in `.gitleaksignore` using `<commit-sha>:<file-path>:<rule-id>:<line-number>` (for git history) and `<file-path>:<rule-id>:<line-number>` (for directory scans).
  - Audited exceptions: deterministic SHA-256 test/identity integrity digests (`docs/evaluation/v*/verification.json`, `docs/verification/phase-b-image.json`) and public Hugging Face model commit revisions (`docs/evaluation/v3/*.json`).
  - Unexplained findings must never be baselined without maintainer investigation.
- **Canary Validation:** Verified using controlled synthetic secrets in untracked files to guarantee positive detection (exit code 1) and redaction without leaking tokens into logs or git history.
- **Scanning Scope & Limitations:**
  - Historical scanning inspects commits present in the active git graph (`fetch-depth: 0`); it cannot prove that secrets were never committed in rewritten history, force-pushed commits, or unpushed transient states outside this repository.
  - Directory scanning (`gitleaks dir .`) is unconstrained by `.gitignore`; developers must use Git-aware commands or targeted paths to avoid false positives from local runtime caches and virtual environments.

---

## 7. Security Review Checklist (apply before merging security-relevant changes)

- [ ] New/changed tool has an explicit, minimal permission scope
- [ ] All SQL is parameterized
- [ ] No secrets or unredacted PII introduced into logs
- [ ] No secrets detected by Gitleaks (`gitleaks git --pre-commit --staged --verbose --redact`)
- [ ] RBAC checks present on any new case-mutating endpoint
- [ ] Retrieved/external content is not used as an instruction source
- [ ] Output validated against expected schema before persistence
- [ ] Evidence/citation references are validated as resolvable, not accepted blindly

---

## 8. Related Documents

`docs/AI_SAFETY_AND_GUARDRAILS.md` (behavioral/evidence constraints), `docs/OBSERVABILITY_AND_AUDIT.md` (logging detail), `docs/TESTING.md` §"Security Testing", `docs/DATABASE_SCHEMA.md` (redaction-relevant columns).


### Portfolio source-grant correction

Forward migration `c832e05a1201` revokes application INSERT/UPDATE on `entities`
and `graph_relationships`, and UPDATE on `alerts`. Current production paths only
read graph source rows; graph loading uses the loader role. Alert intake still
requires INSERT, which is retained. No historical migration is changed. Effective
permissions across all public tables were inspected, not inferred from old SQL;
`verification/portfolio-grants-before.json` records the pre-migration matrix.
Case, investigation, evidence and audit writes retain their established grants.


Final human dispositions (APPROVE and REJECT) require a COMPLETE run with a valid
evidence-backed report and recommendations, per the maintainer's 2026-10-26
clarification in DESIGN.md. Triage actions preserve existing RBAC and allow
missing/incomplete/failed investigations. Active runs block all decisions. Audit
failure or report validation failure cannot leave a changed case status.
