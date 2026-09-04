# ADR-0002: PostgreSQL (+pgvector, adjacency tables) vs. a Separate Graph Database

Status: Accepted
Date: Initial documentation pass (project inception)

## Context

Meridian needs to (a) store and query structured relational financial data, (b) perform vector similarity search over policy document chunks for RAG, and (c) build and analyze an entity/transaction graph for pattern detection (per the brief's Graph Intelligence section). The brief suggests Neo4j as a potential graph database.

## Decision

Use a single **PostgreSQL** instance for all three needs: relational tables for structured data, **pgvector** for embeddings, and an adjacency-list table pattern (`entities` + `graph_relationships`, `docs/DATABASE_SCHEMA.md` §4.5–4.6) plus in-process **NetworkX** analysis for graph construction and algorithms, for MVP and Phase 2.

## Alternatives Considered

- **Neo4j (or another dedicated graph database)** — deferred, not rejected outright. At the synthetic dataset sizes used in this project (analyst-workbench scale, bounded hop-depth queries per `docs/ARCHITECTURE.md` §4.3), PostgreSQL adjacency tables plus NetworkX are sufficient and avoid introducing a second database technology, a second set of operational concerns (backup, access control, schema management), and a second query language for engineers/reviewers to reason about.
- **Dedicated vector database (e.g., Pinecone, Weaviate)** — rejected for the same reason: unjustified operational complexity at this scale when pgvector satisfies the requirement inside the existing database.

## Consequences

- Simpler operational footprint: one database to provision, back up, secure, and audit.
- Graph query expressiveness is bounded by adjacency-table joins + NetworkX in-process analysis, which is adequate for the bounded-depth, moderate-node-count subgraphs this project's use case requires (single-customer/case investigation scope, not whole-bank-graph analytics).
- If a future phase requires whole-graph analytics at a scale PostgreSQL/NetworkX cannot reasonably handle (e.g., true production bank-wide graph scale), that would require a new ADR superseding this one, with a demonstrated performance requirement as justification — not adopted speculatively.
