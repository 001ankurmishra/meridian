# Stage 5A offline foundation — review ready

Implemented: authenticated read-only evidence packages; thin provider protocol;
structured extractive summary/explanation claims; deterministic mock; strict
schema, citation/category/numeric/whole-passage checks; explicit abstention;
timeout/error fallback; versioned mechanical benchmark and cost estimator.
No model has generated or improved a Meridian report. Real semantic faithfulness,
latency, token usage and cost remain NOT MEASURED. Independent review is pending.

## Boundary and security

`load_package(engine, bearer_token, case_id, run_id)` verifies the existing opaque
token and report-view RBAC, case assignment, exact case/run association, and token
validity/assignment again within a repeatable-read, read-only transaction. Existing
assemble_report revalidates persisted evidence producers, sources, finding links
and recommendations. Package loading rejects active/failed runs and returns a
constant UNAVAILABLE error for access/data/database failures. Invalid run or
record details are not returned to the caller. Authentication is snapshot-based,
not a promise that later revocation can erase an already delivered draft.

`package_report` is an internal pure projection for trusted assembled reports and
synthetic tests; it is not an authenticated API. No public route or UI is added.
Packages omit customer names and raw source objects, but recorded text may still
contain sensitive information: this is minimization, **not anonymization**.
Evidence IDs remain exact and all categories retain their original finding links.
This verifies investigation ownership, not universal customer ownership of every
legitimate graph/counterparty source; existing deterministic source selection is
not replaced or independently revalidated by a language model.

The provider receives strings only: system instruction, bounded package JSON,
output schema. It gets no database handle, SQL/tool executor, credentials, case
mutation API or free-form user prompt. Sources are untrusted. Document-linked
passages are omitted entirely in v1 to prevent treating retrieval as policy
applicability. Whole passages over2,000 characters or matching conservative
prohibited/instruction patterns are omitted with a warning; package >100 passages
or64KB is rejected rather than silently truncated. These English heuristics are
not a complete semantic attack detector. Fixed schema and exact extraction
prevent new text from bypassing them; future paraphrasing requires review.

Outputs copy complete recorded passages, category and all evidence IDs exactly.
Changed numbers, swapped subjects, removed negations, foreign/missing citations,
extra fields and nonmatching text fail validation. Numeric checks cannot verify
the source's original arithmetic; source correctness remains deterministic-engine
and reviewer responsibility. A package SHA binds case/run/status/content, not a
cryptographic authorization token. Mock results include model identifier, prompt
version, hash, measured local elapsed time and mandatory limitations.

DRAFT means mechanically accepted **recorded excerpts**. It does not certify
factual truth, complete case coverage, valid policy applicability or independent
semantic entailment. Confidence/missingness remain in the package and mandatory
result limitations. Excerpts may omit important findings: the authoritative
report including sanctions must remain visible when any future UI is approved.
ABSTAIN includes no claims. Invalid output is discarded as UNAVAILABLE; errors and
raw output are not logged. Async timeout assumes cooperative adapters; a future
live client must enforce its own transport deadline and cancellation behavior.
The current deterministic report/state is unchanged on success or failure.

## Evaluation and verification

- Focused initial tests:28 offline passed;5 guarded database tests passed.
- Final integration:124 passed, one existing Starlette/httpx deprecation warning,
  7.34 seconds. Covers new boundary/benchmark plus report assembly/authoring,
  evidence integrity, API authentication, tokens, orchestration and human decisions.
- Ruff passed; mypy passed113 source files. Logs and code/test hashes archived.
- Mechanical benchmark14/14 expected decisions, including a deliberately false
  recorded statement that passes copying. This is **not a14/14 LLM accuracy score**.
- Real-provider calls0; independent semantic examples0; human comparison NOT PERFORMED.
- Full repository suite, Docker rebuild and browser smoke not repeated.

An initial mypy error in the new cost estimator's mixed numeric min expression
was corrected with explicit finite/nonnegative checks; final gates above pass.
The preliminary mechanical receipt is local scratch only; archived receipt binds
final code. No failing assertion was suppressed and no frozen evidence changed.

`PROTOCOL.md` supplies the claim-support rubric, independent-label gate, future
case-level split plan, metric definitions, runtime/usage/cost fields and commands.
`benchmark-v1.json` is a visible synthetic review/DEV fixture, not a sealed test.
No independently reviewed examples were available. Human review and a fresh final
set are required before making provider-quality claims.

## Proposed next step and approval requirements

ADR-0003 remains Proposed. Its appended amendment documents only the authorized
offline exception and a proposed narrow live scope. See `provider-review.md` for
fetched official source links and comparison. Proposed primary: dated GPT-5.4 mini;
alternative: pinned Claude Haiku5.5. This preference is not a measured quality win.
With4k billable input/1k output, listed-price scenarios are $0.0075 and $0.0009 per
request respectively; actual tokenizer/reasoning usage is unknown.

Approval must cover provider/model, retention/privacy/region, API use and budget.
Then implement only that adapter, transport and billing controls and approved
synthetic evaluation. Proposed <=100 calls/$5 pilot is not active or enforced yet.
No runtime exposure until review criteria are satisfied. Free paraphrase, live
bank data, policy applicability and automated recommendations require separate
security/semantic review rather than speculative validation.

No new dependency, framework, service, schema, runtime signal, BGE model, relevance
gate or decision behavior changed. No API key read, paid call, push, merge or deploy.
Stage4 research signals remain unadopted. Goal Mode's broader AIv2 objective is
not declared complete; Stage5A is the authorized offline milestone only.
