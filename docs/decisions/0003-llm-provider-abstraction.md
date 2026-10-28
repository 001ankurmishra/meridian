# ADR-0003: LLM Provider Abstraction

Status: Proposed — specific provider not yet locked in. Note (2026-10-05): as of main ba52a036 there is no LLM provider, LLM call or LLM dependency in the repository and the abstraction was not built; the provider decision is deferred until an LLM-assisted component is explicitly scoped, which requires an ADR update, prompt versioning and hallucination tests per docs/TESTING.md.
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

## Stage 5A scoped implementation and pending amendment (2026-10-27)

Status remains **Proposed**. The maintainer explicitly authorized the offline
foundation before provider acceptance; this does not accept this ADR or activate
live inference. `meridian.copilot.drafts` now implements a thin structured-output
protocol and deterministic mock, separate from the authoritative ReportAgent.
No live adapter, API route, SDK dependency, migration or runtime dispatch is added.

Proposed amendment for approval: restrict initial use to optional human-reviewed,
whole-passage extractive drafts from authenticated case/run packages. Preserve
facts/signals/interpretations/recommendations, exact evidence IDs and uncertainty.
Do not enable free paraphrase, new financial calculations or policy applicability
claims. Record prompt version, model identifier and package hash. Invalid output,
provider failure or timeout discards the entire draft; the deterministic report
remains usable. Source-text fidelity is not independent factual validation.

Provider proposal: one OpenAI GPT-5.4 mini snapshot adapter; Claude Haiku 5.5 is an
alternative only. See [provider review](../evaluation/v5/provider-review.md) for
current official sources, privacy caveats, proposed limits and cost assumptions.
Before acceptance, obtain explicit provider, privacy/retention, budget and API-use
approval. Then implement the selected adapter and billing/transport controls,
review benchmark labels, and measure synthetic outputs before runtime exposure.
No change to ADR-0005, human decisions, BGE-small or Stage4 signal adoption.

## Stage 5B readiness amendment (2026-10-27) — still Proposed

An isolated disabled Responses REST adapter now exists for the proposed
`gpt-5.4-mini-2026-03-17` snapshot, tested only with httpx.MockTransport. It accepts
only byte-identical hash-pinned synthetic fixtures and fixed prompt/schema pairs.
No live provider is selected/accepted by this implementation. Activation requires
an explicit maintainer decision and reviewed approval record; an API key or
environment flag alone cannot enable the current code.

Prepared controls: one-host persistent locked budget ledger, at most100 attempts,
estimated$5 ceiling,8k input estimate/2k output cap, full preflight reservation,
usage reconciliation including reasoning, conservative unknown-usage accounting,
timeout/cancellation, no retries/tools/redirects and store=false. Exact spending
cannot be guaranteed. Experimental paraphrases remain unavailable pending
independent semantic review; citation validity does not certify claim support.

Recovery boundary: a separate mode-0600 initialization record binds the ledger
configuration to the pilot ID. Ledger operations and the live adapter require that
record and matching ID; losing the ledger and lock while the record remains stops
the pilot instead of silently resetting accounting. The record is local and is not
a cryptographic or independent anchor. Loss or alteration of all local accounting
state cannot be distinguished from first initialization; preserve a durable
independent copy and reconcile provider billing before recovery. Therefore the
estimated $5 budget is not an unconditional hard spending guarantee.

The exact proposed provider/privacy/budget/mode decision, limitations and activation
steps are in [Stage5B approval](../evaluation/v5b/APPROVAL.md). Accepting this ADR,
activating calls or changing report/runtime behavior requires separate approval.
