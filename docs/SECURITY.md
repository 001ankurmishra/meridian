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
| **Secrets exposure** | No secrets in source control; environment-variable-based config with a documented `.env.example`; secrets scanning in CI (Phase 3). |
| **Model manipulation** | Model/provider selection is abstracted (`docs/ARCHITECTURE.md` §6); output from the model is validated against expected schema before being used downstream (e.g., a "finding" object must match a defined structure — reject and flag if it doesn't). |
| **Untrusted external content** | Any externally sourced content (documents, alert payloads) is validated and provenance-tagged before entering the evidence pipeline. |
| **Hallucinated evidence / fabricated citations** | Evidence records must reference real rows in the database (`findings.evidence_ids` FK-validated); a citation with no resolvable source record is a hard validation failure, not a warning. |

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

## 6. Security Review Checklist (apply before merging security-relevant changes)

- [ ] New/changed tool has an explicit, minimal permission scope
- [ ] All SQL is parameterized
- [ ] No secrets or unredacted PII introduced into logs
- [ ] RBAC checks present on any new case-mutating endpoint
- [ ] Retrieved/external content is not used as an instruction source
- [ ] Output validated against expected schema before persistence
- [ ] Evidence/citation references are validated as resolvable, not accepted blindly

---

## 7. Related Documents

`docs/AI_SAFETY_AND_GUARDRAILS.md` (behavioral/evidence constraints), `docs/OBSERVABILITY_AND_AUDIT.md` (logging detail), `docs/TESTING.md` §"Security Testing", `docs/DATABASE_SCHEMA.md` (redaction-relevant columns).
