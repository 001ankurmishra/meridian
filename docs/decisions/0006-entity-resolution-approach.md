# ADR-0006: Entity-Resolution Approach (Phase 2)

Status: Accepted
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

D1. ACCEPTED: We will adopt a **deterministic, rule-based entity-resolution approach** rather than an LLM-based generative approach. This aligns with F13 (explainability).

The accepted first slice is narrowly defined as a computation-only, read-only approach matching on:
* exact equality after a fixed normalization specification for `customers.full_name`
* AND exact equality of `customers.date_of_birth`

Normalization version 1 should be:
* Unicode NFKC normalization
* Unicode case folding
* collapse each run of Unicode whitespace to one space
* trim leading/trailing whitespace

Version 1 does NOT include:
* punctuation removal
* diacritic stripping
* token reordering
* initials/abbreviation expansion
* nickname mapping
* transliteration
* phonetic matching
* edit distance
* fuzzy similarity thresholds

Any change to the normalization procedure requires a new normalization version.
Missing/empty name or missing DOB must not produce a candidate. No imputation.

The result is a **candidate entity link for human review**. It must never be described as proof or determination that two customer records represent the same person.
Note: The current schema lacks additional identifier fields. This is a current schema limitation rather than an eternal domain property.

Future fuzzy/learned approaches may remain explicitly deferred alternatives, but nothing in this ADR authorizes their implementation.

D2. Source-data immutability must be strictly preserved. Entity resolution will not alter existing customer, account, or transaction records in the primary tables.

D3. GraphAgent will remain read-only. It will consume resolved entity links but will not perform or persist entity resolution itself. The resolution execution model (e.g., batch process, API endpoint, or dedicated process) remains flexible, provided it accepts explicit, auditable inputs and produces traceable resolved entity links.

D4. Consistent with ADR-0005, we will not make evaluation claims for ER using the current synthetic generators (which lack planted near-duplicates or aliases). We must plant variant customer records in the fixture generation before we can evaluate ER performance.

D5. DEFERRED: Storage of ER links. The first ER slice:
* computes candidates on demand
* operates in memory
* is read-only
* does not persist ER links
* does not modify `graph_relationships`
* does not create a new persistence table
* does not add a migration
* does not wire ER into GraphAgent, evidence, reports, or UI

The following remain open for a future explicit decision:
* on-demand computation
* existing `graph_relationships`
* dedicated ER persistence

D6. We will adhere to the ADR-0002 architecture (PostgreSQL + NetworkX), ensuring ER edges can be seamlessly integrated into graph queries and NetworkX analysis.

## Alternatives Considered

- **LLM-based generative entity matching:** Rejected due to latency, cost, and the lack of deterministic explainability required for financial investigations. Conventional ML techniques (e.g., supervised record linkage) remain open for future consideration if rule-based methods prove insufficient, but are not proposed for this iteration.
- **In-place deduplication / record merging:** Rejected because it violates source-data immutability and auditability rules.

## Consequences

- Entity resolution will be highly transparent, auditable, and rule-based.
- D5 is DEFERRED. Persistent storage requires a separate future decision.
- We cannot build ER until we first add new fixtures with aliases and variant records, ensuring we have data to test against without violating ADR-0005.

## PROHIBITED
- Do not implement ER.
