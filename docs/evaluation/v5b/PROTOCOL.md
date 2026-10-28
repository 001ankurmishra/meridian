# Synthetic explanation pilot protocol v1 — review pending

These 13 new visible synthetic cases cover supported findings, missing/conflicting
records, wrong numbers, fabricated citations, instruction injection, unsupported
regulatory conclusions, ambiguous sanctions, cross-run output, timeout/failure,
a semantic role-swap trap and omitted uncertainty. Fixture byte hash is pinned in
`meridian.copilot.synthetic`; no arbitrary synthetic flag is accepted. No prior
Stage 1–5A evaluation is modified. Labels are AI-authored proposals, not independent
truth. This corpus is DEV/review only, not a held-out final evaluation set.

## Mechanically tested versus independently reviewed

| Measure | Automated readiness behavior | Independent judgment still required |
|---|---|---|
| Schema compliance | Strict Pydantic object, limits, types and no extra fields | Whether explanation is useful |
| Citation validity | Exact package/run binding, passage/category and all evidence IDs | Whether cited facts actually support claim meaning |
| Numeric fidelity | Numeric tokens must match the cited passage's sequence | Correct subject, unit, denominator, currency and arithmetic in underlying evidence |
| Semantic support | Always null/unmeasured in mock results | Supported / contradicted / insufficient / inapplicable for each claim |
| Abstention | No claims on abstention; format checked | Appropriate abstention versus unnecessary refusal |
| Unsupported claims | Obvious violations rejected; no rate inferred from mocks | Claim-level numerator/denominator with independent labels |
| Omissions / contradictions | Required limitation list preserved; some numeric conflicts rejected | Conflicting sources, negation, missing context and misleading selective coverage |
| Latency | Local mock end-to-end and ledger timings | Real provider p50/p95 and transport failures |
| Tokens / cost | Mock reported usage isolated under mock_accounting | Provider-reported billable input/output/reasoning and estimated USD; invoice reconciliation separately |

The semantic role-swap case retains the same number and citations but changes its
meaning. Mechanical checks pass and the result remains UNAVAILABLE with
SEMANTIC_REVIEW_REQUIRED. No model-supplied 'verified' flag is accepted. All
experimental paraphrases stay unavailable, even benign supported-looking ones;
this code contains no automatic release/reviewer bypass. Stage5A extractive mode
is preserved unchanged. Prohibited-text heuristics are English defense-in-depth,
not complete multilingual or semantic classifiers.

Review package: inspect each fixture's original source and limitations alongside
the actual candidate and exact source references. Use the Stage5A human rubric for
subject/time/negation/currency, source applicability, contradictory evidence and
uncertainty. Record reviewer identity, independence, date, candidate hash, claim
index, verdict, rationale and resolution of disagreements. Template in this
folder has null values intentionally. No independent reviewed cases are available.

Before a live measurement: explicitly approve protocol/hash/modes, number of calls,
repetitions and error policy. Do not tune on final results. A fresh final validation
set requires new case-level fixtures and independent review; never call these
visible examples untouched. Do not infer real-world AML accuracy.

Live per-request record must include fixture/package/prompt/schema/code hashes,
exact model, request ID when available, mode, output hash, status, schema/citation/
numeric flags, reviewed semantic results, abstention correctness, latency, provider
input/output/reasoning/cached counts, estimated charge and accounting disposition.
Keep unknown metrics null. Output_tokens already includes reasoning; don't add it
twice. Report separate denominators for received responses, accepted outputs and
independently reviewed claims. Bootstrap by case only with enough reviewed cases;
otherwise uncertainty is not estimable. No false precision from13 examples.

## Reproduction without network or keys

Use repository root and the existing Python 3.11 locked dev environment. Initialize
a new mock ledger explicitly, once, with `v5b-mock-review-v1` before running. The
initializer writes a pilot-bound `.init.json` record; the runner never initializes
or repairs a ledger. Missing/corrupt ledger, lock or initialization record fails
closed, and a populated ledger is refused. Use new ledger and output paths for every
mock run. No record is overwritten. The CLI has no live mode.

```sh
set -eu
mkdir -p scratch/copilot-v5b-reproduce
PYTHONPATH=src UV_NO_SYNC=1 UV_PYTHON=3.11 uv run --frozen --no-sync python -c 'from pathlib import Path; from meridian.copilot.budget import BudgetLedger; BudgetLedger(Path("scratch/copilot-v5b-reproduce/budget.json"), pilot_id="v5b-mock-review-v1").initialize()'
PYTHONPATH=src UV_NO_SYNC=1 UV_PYTHON=3.11 uv run --frozen --no-sync python -m meridian.evaluation.copilot_pilot scratch/copilot-v5b-reproduce/budget.json scratch/copilot-v5b-reproduce/results.json
uv run --frozen --no-sync pytest --offline-unit-tests -q tests/test_openai_pilot.py tests/test_pilot_budget.py tests/test_copilot_explanations.py
```

The preserved initial mock result contains 13/13 expected mechanical outcomes, not an LLM quality score.
Compare outcomes and source hashes; UUID reservation IDs and elapsed times vary.
Actual model executed=null, live requests0, actual usage/cost=null and semantic
faithfulness NOT_MEASURED. Mock provider usage is deliberately fabricated test
input and must never be presented as observed API billing.
