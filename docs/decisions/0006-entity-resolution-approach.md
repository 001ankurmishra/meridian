# ADR-0006: Entity-Resolution Approach (Phase 2)

Status: Proposed
Date: 2026-10-03

## Context

Phase 2 requires entity resolution to detect duplicate or variant customer profiles and hidden relationships.
Before designing the approach, we must acknowledge the current repository state:

- FACT: No entity resolution implementation currently exists in `src` or `tests`.
- FACT: Current synthetic fixtures use standard naming conventions (`Synthetic <suffix> <fixture id>`) and identical dates of birth (`1980-01-01`).
- FACT: No fixture generator or loader currently creates aliases, near-duplicate names, duplicate customer identities, or variant customer records.
- FACT: The schema defines `customers` and `accounts` tables linked via an `entities` abstraction.
- FACT: The GraphAgent operates with read-only permissions over the graph.
- FACT: ADR-0002 mandates PostgreSQL and NetworkX for graph construction.
- FACT: ADR-0005 prohibits performance claims from generator-defined evaluation relationships without independent validation.

## Decision (Proposed)

D1. PROPOSED: We will adopt a **deterministic, rule-based entity-resolution approach** (e.g., exact matches on identifiers, deterministic string similarity thresholds, exact DOB matching) rather than an LLM-based generative approach. This aligns with F13 (explainability).

D2. Source-data immutability must be strictly preserved. Entity resolution will not alter existing customer, account, or transaction records in the primary tables.

D3. GraphAgent will remain read-only. It will consume resolved entity links but will not perform or persist entity resolution itself. The resolution execution model (e.g., batch process, API endpoint, or dedicated process) remains flexible, provided it accepts explicit, auditable inputs and produces traceable resolved entity links.

D4. Consistent with ADR-0005, we will not make evaluation claims for ER using the current synthetic generators (which lack planted near-duplicates or aliases). We must plant variant customer records in the fixture generation before we can evaluate ER performance.

D5. OPEN: Storage of ER links. The maintainer must choose between:
    - on-demand candidate links (computed at runtime in memory)
    - the existing `graph_relationships` table (adding a new relationship type)
    - a new persistence table dedicated to entity resolution

D6. We will adhere to the ADR-0002 architecture (PostgreSQL + NetworkX), ensuring ER edges can be seamlessly integrated into graph queries and NetworkX analysis.

## Alternatives Considered

- **LLM-based generative entity matching:** Rejected due to latency, cost, and the lack of deterministic explainability required for financial investigations. Conventional ML techniques (e.g., supervised record linkage) remain open for future consideration if rule-based methods prove insufficient, but are not proposed for this iteration.
- **In-place deduplication / record merging:** Rejected because it violates source-data immutability and auditability rules.

## Consequences

- If D1 is accepted, entity resolution would be highly transparent, auditable, and rule-based.
- D5 remains OPEN and requires maintainer approval before any implementation work begins.
- We cannot build ER until we first add new fixtures with aliases and variant records, ensuring we have data to test against without violating ADR-0005.

## PROHIBITED
- Do not implement ER.
- Do not close D5.
