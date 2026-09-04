# ADR-0003: LLM Provider Abstraction

Status: Proposed — specific provider not yet locked in
Date: Initial documentation pass (project inception)

## Context

The brief lists OpenAI, Gemini, Anthropic, "or another appropriate provider" as candidates. Agent code (`docs/ARCHITECTURE.md` §4) needs to call an LLM for reasoning/synthesis tasks (primarily in `ReportAgent`, and potentially lightweight reasoning in `TransactionAgent`/`GraphAgent`/`PolicyAgent`). Hard-coupling agent logic to one vendor's SDK would make provider changes, cost comparisons, or local/offline testing harder.

## Decision (Proposed)

Introduce a thin internal LLM-client interface (e.g., `generate_structured(prompt, schema, ...) -> ParsedOutput`) that all agents call, with a single provider-specific implementation behind it selected via configuration. **Specific provider selection is deferred** — this ADR proposes the abstraction pattern, not the final vendor choice, which should be recorded as an update to this ADR (or a superseding ADR-0003a) once decided, along with the rationale (cost, structured-output support, latency, evaluation results).

## Alternatives Considered

- **Direct SDK coupling to a single provider from the start** — rejected: increases switching cost and makes `docs/EVALUATION.md`'s agent-cost/latency comparisons harder to run fairly across providers if that's ever useful.
- **Multi-provider routing/fallback logic in the MVP** — rejected as premature; adds complexity (`CLAUDE.md` §10 "do not over-engineer") not justified until there's an actual reliability requirement driving it (candidate for Phase 3 "reliability" work, `docs/ROADMAP.md`).

## Consequences

- Slightly more upfront interface design work in exchange for provider flexibility later.
- Every LLM call remains versioned via `prompt_version` and `model_identifier` fields (`docs/DATABASE_SCHEMA.md` §4.11) regardless of provider, preserving auditability (`docs/OBSERVABILITY_AND_AUDIT.md`) independent of this choice.
- **Action required before Phase 1 implementation begins:** update this ADR's Status to Accepted once a specific provider is chosen, with the rationale recorded.
