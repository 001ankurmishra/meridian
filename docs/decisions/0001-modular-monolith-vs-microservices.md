# ADR-0001: Modular Monolith vs. Microservices

Status: Accepted
Date: Initial documentation pass (project inception)

## Context

The original project brief's suggested architecture implies a fairly distributed system: separate agent services, Kafka streaming, Redis, multiple potential databases. Project Meridian is a portfolio/engineering-demonstration system with a single-analyst-workbench usage pattern (not real production transaction volume), built and maintained by a small team (effectively one engineer during the primary build phases).

## Decision

Build Meridian as a **modular monolith**: one deployable FastAPI backend with clearly separated internal modules (`docs/ARCHITECTURE.md` §3), rather than separate microservices per agent or per capability, at least through Phase 3 (Production Readiness).

## Alternatives Considered

- **Full microservices per agent** — rejected for MVP/Phase 2/3: no demonstrated scaling requirement justifies the operational overhead (deployment complexity, inter-service auth, network failure modes) at this project's actual usage scale. Would also slow iteration speed during the phases where the investigation logic itself is still being refined.
- **Event-driven architecture (Kafka-based) from the start** — rejected: no real-time/high-throughput alert stream exists in this project; alerts arrive at analyst-workbench scale. A simple queue/background-job pattern is sufficient if async processing is ever needed.

## Consequences

- Easier to reason about, test, and audit as a single codebase with enforced module boundaries.
- Module boundaries (§3 of `docs/ARCHITECTURE.md`) are kept clean specifically so a future split into services remains possible without a full rewrite, should a genuine scaling need ever arise (unlikely for this project, but the design doesn't foreclose it).
- Revisit this decision only if a concrete requirement emerges that a monolith cannot satisfy (e.g., independently scaling one agent's compute-heavy workload) — such a change requires a new ADR, not an ad hoc migration.
