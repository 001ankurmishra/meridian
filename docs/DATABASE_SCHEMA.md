# Database / Data Model — Project Meridian

**Read every coding session?** Yes, for any change touching data.

**Status of this document:** PROPOSAL. This is the target relational schema (PostgreSQL). Treat table/column names here as the source of truth once migrations are created; until then, this is the design to implement against, not a description of an already-existing database. When implementation begins, this file must be kept in sync with actual migrations — divergence is a documentation defect (`CLAUDE.md` §9).

---

## 1. Design Principles

- **PostgreSQL only** for the MVP/Phase 2 — structured data, graph edges (adjacency-list tables), and vector embeddings (pgvector) all live in one instance. See ADR-0002.
- **Source vs. derived vs. AI-generated vs. human-generated data is explicit** — see §3. AI-generated data never overwrites authoritative source records.
- **Every table has provenance** — `created_at`, `created_by` (system/agent/human identifier), and where relevant `source` (e.g., "AMLSim import", "synthetic generator v1", "TransactionAgent run #123").
- **Soft deletion** is used for anything with compliance/audit relevance (cases, evidence, findings, documents); hard deletes are reserved for genuinely transient data (e.g., cache-like tables, if any).
- Not every entity brainstormed in the original brief is included — entities without a clear MVP or near-term Phase-2 use are deferred (see §6).

---

## 2. Entity Overview

```
customers ──< accounts ──< transactions >── counterparties (self-referential via accounts/entities)
customers ──< beneficiaries
accounts, customers, beneficiaries, devices ──< entities (unified entity view) ──< graph_relationships
alerts ──< cases ──< investigation_runs ──< agent_runs
investigation_runs ──< evidence ──< findings ──< recommendations
documents ──< document_chunks (RAG corpus)
investigation_runs, agent_runs, cases, review decisions ──< audit_events (append-only)
risk_signals references transactions/customers/investigation_runs
users/roles support RBAC across cases and agent-run authorization
```

---

## 3. Data Provenance Categories

| Category | Examples | Mutability Rule |
|---|---|---|
| **Source data** | `customers`, `accounts`, `transactions`, `beneficiaries` (loaded from AMLSim/PaySim/synthetic generator) | Immutable after import except through a documented, audited correction process. Never overwritten by AI output. |
| **Derived data** | `risk_signals`, computed aggregates used in findings | Recomputable from source data; versioned by `investigation_run`/model version. |
| **AI-generated data** | `findings`, `recommendations`, draft report text, agent-produced `evidence` links | Always attributed to an `agent_run`; never promoted to source-data status; always subject to human review before being treated as case-affecting. |
| **Human-generated data** | `case_notes`, review decisions, manual evidence annotations | Authoritative for case disposition; only humans can change case status. |

---

## 4. Core Tables (MVP + Phase 2 scope)

### 4.1 `customers`
| Column | Type | Notes |
|---|---|---|
| `customer_id` | UUID PK | |
| `full_name` | text | synthetic |
| `date_of_birth` | date | synthetic |
| `kyc_risk_rating` | text | enum: LOW/MEDIUM/HIGH; source data |
| `onboarded_at` | timestamptz | |
| `source` | text | e.g. "amlsim_import_v1" |
| `created_at` | timestamptz | |
| `is_synthetic` | boolean NOT NULL DEFAULT true | **must always be true in this project** — see `docs/DATA_AND_DATASET_STRATEGY.md` |

### 4.2 `accounts`
| Column | Type | Notes |
|---|---|---|
| `account_id` | UUID PK | |
| `customer_id` | UUID FK → customers | |
| `account_type` | text | savings/current/etc. |
| `opened_at` | timestamptz | |
| `status` | text | active/closed/frozen — **frozen only settable via human-approved workflow, never directly by an agent** |
| `created_at` | timestamptz | |

Index: `(customer_id)`.

### 4.3 `transactions`
| Column | Type | Notes |
|---|---|---|
| `transaction_id` | UUID PK | |
| `source_account_id` | UUID FK → accounts, nullable | |
| `destination_account_id` | UUID FK → accounts, nullable | |
| `amount` | numeric(18,2) | |
| `currency` | text | default INR for worked examples |
| `transaction_type` | text | transfer/payment/etc. |
| `occurred_at` | timestamptz | |
| `counterparty_external_ref` | text, nullable | for transactions leaving the synthetic universe |
| `source` | text | dataset origin (AMLSim/PaySim/synthetic-generator) |
| `created_at` | timestamptz | |

Indexes: `(source_account_id, occurred_at)`, `(destination_account_id, occurred_at)`.

### 4.4 `beneficiaries`
| Column | Type | Notes |
|---|---|---|
| `beneficiary_id` | UUID PK | |
| `customer_id` | UUID FK → customers | |
| `account_id` | UUID FK → accounts, nullable | beneficiary's own account if internal |
| `added_at` | timestamptz | used for "newly created beneficiary" signal |
| `created_at` | timestamptz | |

### 4.5 `entities`
Unified view/table over customers, accounts, beneficiaries, devices, merchants — used as graph nodes.
| Column | Type | Notes |
|---|---|---|
| `entity_id` | UUID PK | |
| `entity_type` | text | customer/account/beneficiary/device/merchant |
| `reference_id` | UUID | FK to the underlying specific table (polymorphic; enforced in application layer, not DB FK, per Postgres polymorphic-association limitations — **ASSUMPTION**: acceptable tradeoff at this scale; revisit if integrity issues arise) |
| `created_at` | timestamptz | |

### 4.6 `graph_relationships`
| Column | Type | Notes |
|---|---|---|
| `relationship_id` | UUID PK | |
| `source_entity_id` | UUID FK → entities | |
| `target_entity_id` | UUID FK → entities | |
| `relationship_type` | text | transfer/shared_device/shared_address/ownership/etc. |
| `weight` | numeric, nullable | e.g. transaction amount or count for transfer edges |
| `first_observed_at` | timestamptz | |
| `last_observed_at` | timestamptz | |
| `created_at` | timestamptz | |

Indexes: `(source_entity_id)`, `(target_entity_id)`, `(relationship_type)`.

### 4.7 `devices` (Phase 2)
Deferred until entity-resolution / shared-device signals are implemented (`docs/ROADMAP.md` Phase 2). **PROPOSAL**, not in MVP.

### 4.8 `alerts`
| Column | Type | Notes |
|---|---|---|
| `alert_id` | UUID PK | |
| `customer_id` | UUID FK → customers | |
| `transaction_id` | UUID FK → transactions, nullable | primary triggering transaction, if any |
| `alert_type` | text | e.g. large_transaction, new_beneficiary, rapid_movement |
| `alert_reasons` | jsonb | list of reason codes, source-system generated |
| `raised_at` | timestamptz | |
| `source_system` | text | "synthetic-monitoring-generator" for this project |
| `created_at` | timestamptz | |

### 4.9 `cases`
| Column | Type | Notes |
|---|---|---|
| `case_id` | UUID PK | human-readable code also stored, e.g. AML-48291 |
| `alert_id` | UUID FK → alerts | |
| `status` | text | OPEN / IN_REVIEW / ESCALATED / CLOSED_APPROVED / CLOSED_REJECTED / CLOSED_MORE_INFO |
| `assigned_analyst_id` | UUID FK → users, nullable | |
| `opened_at` | timestamptz | |
| `closed_at` | timestamptz, nullable | |
| `deleted_at` | timestamptz, nullable | soft delete |
| `created_at` | timestamptz | |

### 4.10 `investigation_runs`
| Column | Type | Notes |
|---|---|---|
| `investigation_run_id` | UUID PK | |
| `case_id` | UUID FK → cases | |
| `status` | text | IN_PROGRESS / COMPLETE / INCOMPLETE_INSUFFICIENT_EVIDENCE / FAILED |
| `started_at` | timestamptz | |
| `completed_at` | timestamptz, nullable | |
| `orchestrator_version` | text | for reproducibility |
| `created_at` | timestamptz | |

### 4.11 `agent_runs`
| Column | Type | Notes |
|---|---|---|
| `agent_run_id` | UUID PK | |
| `investigation_run_id` | UUID FK → investigation_runs | |
| `agent_name` | text | e.g. TransactionAgent |
| `tool_calls` | jsonb | structured record of tool invocations (see `docs/OBSERVABILITY_AND_AUDIT.md`) |
| `status` | text | SUCCESS / FAILED / PARTIAL |
| `model_identifier` | text, nullable | LLM/model used, if any |
| `prompt_version`| text, nullable | |
| `started_at` | timestamptz | |
| `completed_at` | timestamptz, nullable | |
| `error` | text, nullable | |

### 4.12 `evidence`
| Column | Type | Notes |
|---|---|---|
| `evidence_id` | UUID PK | |
| `investigation_run_id` | UUID FK → investigation_runs | |
| `evidence_type` | text | transaction/beneficiary/graph/policy_chunk/risk_signal |
| `reference_table` | text | which source table this points to |
| `reference_id` | UUID | polymorphic reference (application-enforced) |
| `produced_by_agent_run_id` | UUID FK → agent_runs | |
| `created_at` | timestamptz | |

### 4.13 `findings`
| Column | Type | Notes |
|---|---|---|
| `finding_id` | UUID PK | |
| `investigation_run_id` | UUID FK → investigation_runs | |
| `observed_fact` | text | |
| `derived_signal` | text, nullable | |
| `interpretation` | text, nullable | |
| `evidence_ids` | UUID[] | must be non-empty for the finding to be included in a report — enforced in application logic |
| `confidence` | text | LOW/MEDIUM/HIGH, methodology documented in `docs/EVALUATION.md` |
| `created_at` | timestamptz | |

### 4.14 `recommendations`
| Column | Type | Notes |
|---|---|---|
| `recommendation_id` | UUID PK | |
| `investigation_run_id` | UUID FK → investigation_runs | |
| `text` | text | e.g. "Escalate case for enhanced human review" |
| `based_on_finding_ids` | UUID[] | |
| `created_at` | timestamptz | |

### 4.15 `policies` / `documents` / `document_chunks`
| `documents` | Notes |
|---|---|
| `document_id` UUID PK | |
| `title` text | |
| `document_type` text | internal_policy / regulatory_guidance |
| `version` text | |
| `source_url_or_ref` text, nullable | |
| `is_synthetic` boolean | if using synthetic policy text |
| `created_at` timestamptz | |

| `document_chunks` | Notes |
|---|---|
| `chunk_id` UUID PK | |
| `document_id` UUID FK → documents | |
| `chunk_text` text | |
| `chunk_index` int | position within document |
| `embedding` vector | pgvector column, dimension per chosen embedding model (**REQUIRES VERIFICATION** once embedding model is selected — record in ADR) |
| `created_at` timestamptz | |

### 4.16 `risk_signals`
| Column | Type | Notes |
|---|---|---|
| `risk_signal_id` | UUID PK | |
| `investigation_run_id` | UUID FK → investigation_runs, nullable | nullable to allow standalone batch scoring |
| `customer_id` | UUID FK → customers | |
| `transaction_id` | UUID FK → transactions, nullable | |
| `signal_type` | text | amount_deviation/velocity/new_counterparty/etc. |
| `value` | numeric, nullable | raw computed value |
| `model_version` | text, nullable | for ML-derived signals |
| `methodology` | text | PROTOTYPE / EXPERIMENTALLY_CALIBRATED / PRODUCTION_APPROVED (see `docs/EVALUATION.md`) |
| `created_at` | timestamptz | |

### 4.17 `audit_events` (append-only)
| Column | Type | Notes |
|---|---|---|
| `audit_event_id` | UUID PK | |
| `case_id` | UUID FK → cases, nullable | |
| `investigation_run_id` | UUID FK → investigation_runs, nullable | |
| `actor_type` | text | agent/human/system |
| `actor_id` | text | agent name or user ID |
| `action` | text | |
| `input_summary` | jsonb | redacted per `docs/SECURITY.md` |
| `output_summary` | jsonb | redacted per `docs/SECURITY.md` |
| `occurred_at` | timestamptz | |

No `UPDATE`/`DELETE` permitted on this table at the application-role level; enforced via DB grants (**PROPOSAL** — to be implemented as a migration-time grant statement).

### 4.18 `users` / `roles` (RBAC)
| `users` | Notes |
|---|---|
| `user_id` UUID PK | |
| `email` text | |
| `role` text | analyst / senior_analyst / compliance_manager / admin |
| `created_at` timestamptz | |

Fine-grained permission mapping (which role can approve/escalate/close) documented in `docs/SECURITY.md` §"Authorization Model."

---

## 5. Denormalization Notes

`entities` intentionally denormalizes a lightweight pointer table over `customers`/`accounts`/`beneficiaries`/`devices` so `graph_relationships` has a single node type to reference rather than a polymorphic mess spread across multiple relationship tables. This trades some referential-integrity strictness (application-enforced FK rather than DB-enforced) for a materially simpler graph query surface. **ASSUMPTION**: acceptable given synthetic-data integrity is fully controlled by our own generators.

---

## 6. Entities Considered and Deferred

The original brief's entity brainstorm included `addresses` and generic `documents` beyond policy documents. Deferred for MVP:
- `addresses` as a first-class table — folded into `entities`/`graph_relationships` metadata for now; promote to a full table only if address-sharing detection becomes a concrete Phase-2 feature.
- `devices` — Phase 2, once device-sharing signals are actually built.

Not deferred arbitrarily — each has a named trigger condition for when it should be added (see above), avoiding both "include everything" and "guess what's needed later" anti-patterns.

---

## 7. Retention & Redaction

See `docs/SECURITY.md` §"Data Retention & Redaction" for the authoritative policy. Summary: `audit_events.input_summary`/`output_summary` must not contain full raw PII fields (e.g., full account numbers) — redact/truncate at write time.

---

## 8. Related Documents

`docs/ARCHITECTURE.md` (which module owns which table), `docs/SECURITY.md` (authorization + redaction), `docs/DATA_AND_DATASET_STRATEGY.md` (how these tables get populated), `docs/DECISIONS.md` ADR-0002 (why PostgreSQL over a separate graph DB).
