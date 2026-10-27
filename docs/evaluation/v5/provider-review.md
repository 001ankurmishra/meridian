# Stage 5 provider proposal — NOT APPROVED

Official documentation reviewed 2026-10-27. No account capability probe, API key,
model request, case transmission or paid call was made. This is a shortlist for
an approved synthetic evaluation, not measured Meridian model quality.

| Criterion | Primary proposal: OpenAI GPT-5.4 mini | Alternative: Anthropic Claude Haiku 5.5 |
|---|---|---|
| Exact model | `gpt-5.4-mini-2026-03-17` snapshot | `claude-haiku-5-5`; modern dateless IDs are pinned versions |
| Structured output | Supported; application validation still mandatory | JSON schema structured outputs supported; application validation still mandatory |
| Quality | Vendor positions it as an efficient capable mini; Meridian faithfulness UNKNOWN | Vendor positions it for extraction/classification; Meridian faithfulness UNKNOWN |
| Latency | Vendor positions it for high-volume work; no local p50/p95 evidence | Vendor positions it for low latency; no local p50/p95 evidence |
| Standard input/output USD per million | $0.75 / $4.50 | $0.10 / $0.50 for prompts <=100k; higher tier beyond that |
| Retention | Default abuse monitoring up to30d; Responses storage must explicitly be disabled; ZDR subject to eligibility and feature exceptions | Standard API inputs/outputs deleted within30d, with legal/policy/service exceptions; ZDR requires agreement |
| Training | API endpoint table says no training | Commercial API no training by default; opt-in/feedback exceptions |
| Stability | Use dated snapshot, re-evaluate version changes | Fixed model ID; serving infrastructure may still change behavior |

Recommend the primary for a single tightly scoped baseline because its dated
snapshot and explicit Responses storage control fit the proposed audit record.
This is an engineering preference, not evidence of superior quality. Haiku has a
substantially lower listed price and is a credible alternative if cost is the
maintainer's priority. Do not implement both adapters or automatic routing.
Both are candidates only; actual availability, regional handling and contractual
privacy must be confirmed before approval/activation. No banking compliance claim.

Cost scenario, not a measured token count:4,000 billable input plus1,000 billable
output tokens per draft, no caching/batch/tools/retries/tax/regional uplift:
OpenAI $0.0075/draft ($0.75/100); Haiku $0.0009/draft ($0.09/100).
Provider tokenizers differ, and reasoning tokens count toward billable output.
A displayed-text limit is not a total cost cap. Proposed pilot: <=100 synthetic
requests, <=8k total input/2k total output per call and $5 maximum cumulative
budget, with preflight reservation and an explicit billing ledger before live
use. These are proposed controls, not implemented billing enforcement.

Proposed configuration (not active): enabled=false; selected provider/model;
max_input_tokens; max_output_tokens; transport_timeout_seconds=10;
max_attempts=1; synthetic_only=true; store=false for OpenAI;
pilot_budget_usd=5. No tools, files, remote retrieval, conversation persistence,
background mode or raw case logs. Use one project-scoped API credential injected
server-side from an OS/environment secret facility, excluded from Git/Docker/UI.
Never ask for keys in chat. Redact exceptions; log model/prompt/package hashes,
validation reason, request identifier, billed usage, latency and cost only.
Require explicit provider + privacy/retention + budget + API-use approval.

Sources (official, fetched):

- [OpenAI model capability, snapshot and price](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
- [OpenAI data controls and endpoint exceptions](https://developers.openai.com/api/docs/guides/your-data)
- [Claude Haiku 5.5 capabilities](https://platform.claude.com/docs/en/models/haiku-5-5/overview)
- [Claude price tiers](https://platform.claude.com/docs/en/about-claude/pricing)
- [Claude structured output compatibility](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude pinned model IDs](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions)
- [Anthropic retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)
- [Anthropic training policy](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)
