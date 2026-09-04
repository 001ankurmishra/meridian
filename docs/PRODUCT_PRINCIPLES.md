# Product & AI Principles — Project Meridian

**Read every coding session?** Yes, for any change touching agent behavior, report generation, or risk scoring.

These five principles govern every product and engineering decision in Meridian. When a feature request or implementation choice conflicts with one of these, the principle wins — raise the conflict per `CLAUDE.md` §9 rather than silently overriding it.

---

## Principle 1 — Evidence Before Conclusions

No finding surfaces to a human without traceable supporting evidence. Every material claim in a report must be attributable to a specific, retrievable record (a transaction ID, a policy document + version, a graph edge, a retrieved chunk with a citation). If evidence is missing, weak, or conflicting, the system says so explicitly rather than smoothing over the gap. See the Fact → Signal → Interpretation → Recommendation chain in `CLAUDE.md` §4 and `docs/AI_SAFETY_AND_GUARDRAILS.md`.

## Principle 2 — AI Assists; Humans Remain Accountable

Meridian augments an analyst's judgment; it does not replace their accountability. The system's outputs are always framed as recommendations requiring human review, never as determinations. This is enforced architecturally (API-level authorization gates on any consequential action), not just through UI copy or prompt instructions.

## Principle 3 — Structured Data and Documents Require Different Retrieval

Facts that live in a database (transaction amounts, counts, timestamps, balances, relationships) are retrieved deterministically via SQL/structured queries. Knowledge that lives in unstructured documents (policy, regulatory guidance, procedures) is retrieved via RAG. Conflating the two — asking an LLM to "remember" a number instead of querying for it — is treated as a bug, not a stylistic choice. See `CLAUDE.md` §5.

## Principle 4 — Every Important AI Action Is Auditable

Any agent/tool invocation that materially affects an investigation's evidence or conclusions is logged with enough context (case ID, agent, tool, input, output, timestamp, model/prompt version) to reconstruct after the fact why the system reached its output. Auditability is a first-class requirement, not an afterthought bolted on before a demo. See `docs/OBSERVABILITY_AND_AUDIT.md`.

## Principle 5 — High-Impact Financial Decisions Are Never Fully Autonomous

Actions with real-world consequence — account freezes, closures, regulatory filings, formal suspicious-activity determinations — always require an explicit, identifiable human approval step, enforced server-side. No amount of model confidence changes this. See `docs/AI_SAFETY_AND_GUARDRAILS.md` §"Prohibited Autonomous Actions."

---

## Applying the Principles: Decision Heuristics

When designing a new feature, ask, in order:

1. **Does this feature ask the AI to state something as fact without a traceable source?** → Redesign so evidence is explicit and citable, or block the claim.
2. **Does this feature let an agent take or trigger an irreversible action?** → It must route through a human-approval gate; no exceptions.
3. **Is this a factual/numeric question about structured data being routed through an LLM/RAG path?** → Reroute to SQL.
4. **Does this feature add a new agent, service, or piece of infrastructure?** → Justify against a demonstrated requirement (`docs/ARCHITECTURE.md` §"Technology Selection"); if not justified, don't add it yet.
5. **Would a human AML analyst find this output auditable and defensible in a real compliance review?** → If not, it's not done.

---

## Non-Goals (explicit)

- Meridian is not trying to demonstrate the largest possible number of AI agents or the most exotic tech stack. Depth and correctness of a smaller, well-justified system beat breadth of components used superficially.
- Meridian does not claim production-bank-grade compliance certification. It claims *engineering discipline modeled on* production banking AI requirements, using public/synthetic data.
- Meridian does not optimize for demo "wow factor" at the expense of evidence integrity. A conservative, well-evidenced HIGH-risk finding is preferred over an impressive-sounding but unsupported CRITICAL one.
