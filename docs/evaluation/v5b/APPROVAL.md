# Stage 5B decision proposal — live pilot NOT approved

ADR-0003 remains Proposed. Offline readiness does not authorize external requests.
The adapter's APPROVED_PILOT_ID is None. An environment flag or API key alone
cannot enable it. No credential was read or live API called during this milestone.

## Precise proposed decision

Approve or amend these together before a live synthetic pilot:

| Item | Proposed scope |
|---|---|
| Provider / model | OpenAI Responses API; only `gpt-5.4-mini-2026-03-17` |
| Data | Only the exact13 checked-in synthetic fixtures and pinned prompt/schema pairs; no database-derived package, names, notes, uploads or user-supplied text |
| Modes | Extractive baseline; separately approve experimental explanation measurement, whose output stays unavailable pending independent review |
| Privacy | `store=false`, synchronous, no tools/files/conversations; accept the provider's documented abuse-monitoring retention and exceptions, or require an approved alternative retention agreement first |
| Budget | At most100 attempted requests; estimated cumulative cap$5; no retries; preflight8k input/2k output reservation at standard uncached rates |
| Transport | Fixed HTTPS endpoint;10s wall/transport deadline; no redirects, environment proxy use, background calls or browsing |
| Accounting | One owner-controlled local ledger, lock and pilot-bound `.init.json` record shared on a single host; missing any file fails closed; preserve all three and reconcile before recovery; no reset, deletion or second ledger for the same pilot |
| Review | Approve fixture/prompt/schema hashes and proposed expectations; appoint independent semantic reviewer; no runtime publication based on model self-grading |

The synthetic corpus SHA256 is recorded in `fixtures-v1.json`'s code-pinned
registry and `mock-results.json`. These are visible development/review cases,
not independently validated labels or an untouched final set.

## Current official documentation confirmation (2026-10-27)

The [model page](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
lists the requested dated snapshot, Responses support, structured outputs and
standard input/output pricing of $0.75/$4.50 per million tokens. Account-specific
availability remains unverified because no key or model request was used.

The [structured output guide](https://developers.openai.com/api/docs/guides/structured-outputs)
documents Responses `text.format` with JSON schema and strict mode. The
[reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
documents output/usage handling, including reasoning within output-token usage.
We use direct REST through the existing locked httpx0.28.1 dependency, not a new
SDK. Mock tests validate the request contract; real endpoint acceptance remains
unverified until an approved pilot. The full API-reference fetch exceeded the
browser tool limit; the fetched official guides establish the implemented fields.

The [data controls guide](https://developers.openai.com/api/docs/guides/your-data)
reports no API training by default and default abuse-monitoring retention up to30
 days, subject to exceptions. `store=false` does not itself grant Zero Data
Retention. ZDR requires eligibility/approval and supported endpoint/features.
No compliance, residence or contractual privacy guarantee is inferred here.

## Data flow and limitations

Checked-in fixture bytes → SHA256 verification → deterministic synthetic case/run,
passage/finding/evidence IDs → exact payload allowlist → fixed prompt/schema →
conservative input bound → durable budget reservation → approved server-side key
and fixed Responses endpoint → bounded response parse → usage reconciliation →
independent mechanical checks → extractive baseline or unavailable experimental
candidate requiring semantic review. No production/demo database is used.

The package is exact synthetic text; it contains no runtime customer records.
Fixture text may intentionally contain hostile instructions for evaluation, but
cannot modify the fixed system instruction, schema, model, destination or tools.
Output text may still be incorrect or contain invented identifiers: quarantine
live synthetic outputs locally for approved review, never auto-publish them.
Operational records contain fixture IDs, prompt versions, counts, timings and
bounded outcome codes, not credentials or provider error bodies. A future real
runner must bind provider output hashes and reviewer decisions before publication.

Use only OPENAI_API_KEY injected server-side from a protected environment/secret
facility. Do not paste a key in chat, commit it, put it in fixture data or expose
it to the UI. Locked pilot/test environment includes httpx in the existing dev
dependencies; there is no new production route or dependency installation.

## Spending and token caveats

Reserve$0.015 per attempted request:8,000 input at$0.75/M plus2,000 output at
$4.50/M. At100 nominal full reservations this is$1.50, below the separate$5 ceiling.
A4k-input/1k-output scenario is$0.0075. These are estimated standard-rate costs,
not invoices; cached input is conservatively charged at the uncached rate.
Reasoning tokens are part of output_tokens and are never added twice.
Unknown usage, timeout, cancellation and crash keep the entire reservation and
consume a request slot. Verified usage reconciles downward or upward; reported
cap overages halt future admission. No ambiguous request is automatically retried.

Initialize with the approved pilot ID exactly once:
`BudgetLedger(path, pilot_id=APPROVED_PILOT_ID).initialize()`. This writes a
separate `.init.json` record containing that ID and the budget configuration.
Reserve/snapshot operations verify the record against the ledger and fail closed
when any of the ledger, lock or record is missing or mismatched. The live adapter
also requires the ledger ID to match its approved pilot ID. The mock runner never
initializes or repairs a ledger. The sidecar detects loss of the ledger and lock
while the record survives; it is not a cryptographic anchor and cannot detect
deletion or deliberate alteration of all local state. Preserve the record
separately in owner-controlled durable storage. Treat any lost/corrupt state as a
stop condition requiring provider-billing reconciliation, never as a fresh pilot.

The request-count and token limits are enforced by code while the pilot-bound
accounting state is intact. The $5 amount is an estimated local admission limit,
not an unconditional hard spending guarantee: the provider may bill differently,
the estimate uses bytes rather than its tokenizer, local accounting can be lost,
and all local files can be altered. Maintain an independent durable copy and
reconcile provider billing before any recovery.

The input guard uses full serialized UTF-8 bytes plus1,024 envelope allowance,
not an exact provider tokenizer. It rejects estimates above8k; actual reported
input/output overages reject output and halt further requests. Server-side billing,
unknown usage, changed rates, provider behavior or deletion of the trusted local
ledger prevent an exact dollar-spending guarantee. File locking is single-host
POSIX only; do not run this pilot on multiple hosts or untrusted/network filesystems.

## Exact activation sequence after explicit approval

1. Record the maintainer's provider/privacy/budget/mode decision and fixture,
   prompt/schema/code hashes in a reviewed approval record; only then update
   ADR-0003 status and bind APPROVED_PILOT_ID to that approved pilot.
2. Reconfirm model access/rates and accepted retention settings; designate one
   durable ledger path and owner. Do not reuse/reset uncertain prior accounting.
3. Initialize the ledger once with the exact approved ID using
   `BudgetLedger(path, pilot_id=APPROVED_PILOT_ID).initialize()`. Preserve its
   ledger, lock and `.init.json` record together, with a separate durable copy of
   the record. Inject the credential outside Git/chat; set MERIDIAN_SYNTHETIC_PILOT_ENABLED
   to the approved pilot ID. No variable is enabled by this readiness commit.
4. Run one approved synthetic smoke request through this adapter, with the fixed
   schema and deadline. Confirm usage and endpoint behavior before further calls.
5. Run the approved finite fixture set, preserving real usage/cost/latency separately
   from mock evidence. Review unsupported claims, omissions and contradictions
   independently. Do not release paraphrases or change authoritative findings.
