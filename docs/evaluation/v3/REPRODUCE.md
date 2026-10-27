# Reproduce Stage 3 DEV experiments

Use Python 3.11 and the existing locked environment. No new dependency is needed.
Use the disposable database role URLs and guard setup documented in
`../v2/REPRODUCE.md`; never point these commands at the demo database.
Set `PYTHONPATH=src`, `UV_NO_SYNC=1`, `UV_PYTHON=3.11` and
`HF_HUB_DISABLE_TELEMETRY=1`. Downloads require public Hugging Face access;
no token or paid inference service is required. The runner explicitly disables
credential transmission to the Hub and remote model code, and permits only
safetensors weights with the manifest's exact published size and SHA256.

The source corpus must be the existing `scratch/ai-v2/references/chunks-v2.jsonl`.
Its hash is validated against the DEV protocol before model loading. It can be
reproduced using the v2 ingestion instructions. No IBM reprocessing is needed.

Run each model in its own process so process peak RSS is not contaminated by a
previous model. The following output paths must not already exist. Existing
`.started.json` files require inspecting the process and logs before any retry;
do not remove a receipt or launch duplicate downloads just because output pauses.

```sh
uv run --frozen --no-sync python -m meridian.evaluation.external.experiment \
  docs/evaluation/v3 scratch/ai-v2/references/chunks-v2.jsonl \
  scratch/ai-v3/small.json --model-index 0
uv run --frozen --no-sync python -m meridian.evaluation.external.experiment \
  docs/evaluation/v3 scratch/ai-v2/references/chunks-v2.jsonl \
  scratch/ai-v3/base.json --model-index 1
```

Use cached scores to compare ungated positive nDCG. Pick the stronger embedder
(ties choose small) for the one cross-encoder experiment. Pass that result as
`--first-stage`; this preserves the 50-candidate pool, including candidates that
would have been rejected by a query gate. The reranker receives raw query and
passage pairs, returns raw logits, and uses the same float32 CPU/thread setting.

```sh
uv run --frozen --no-sync python -m meridian.evaluation.external.experiment \
  docs/evaluation/v3 scratch/ai-v2/references/chunks-v2.jsonl \
  scratch/ai-v3/reranker.json --model-index 2 \
  --first-stage scratch/ai-v3/small.json
uv run --frozen --no-sync python -m meridian.evaluation.external.comparison \
  docs/evaluation/v3 scratch/ai-v2/references/chunks-v2.jsonl \
  scratch/ai-v3/comparison.json scratch/ai-v3/small.json \
  scratch/ai-v3/base.json scratch/ai-v3/reranker.json
```

Small won the predefined ungated DEV nDCG rule; the selection receipt is
`reranker-selection.json`. Never substitute based on HELDOUT.
Vectors are cached as non-pickle JSON with a configuration digest; analysis and
reranking reuse scores/candidates without re-encoding the corpus. Model snapshots
are reused by immutable revision. Outputs are never silently overwritten.

Timing: weight retrieval/hash validation, model construction/load, document
embedding and warmed query work are separate. Model-loading timing excludes
Python/library imports and download; mmap page faults can occur in subsequent
inference. Warm measurements include one excluded warm-up. Reranking timing
excludes upstream retrieval, which must be added for end-to-end latency.
Peak RSS is whole-process lifetime high-water mark including libraries and
embedding batches, not model-weight size or isolated query working memory.
These are single-process CPU observations, not a concurrent deployment SLA.

Source-eligibility rules are experimental and conservative: explicit internal
Meridian, domestic legal-source, and absent-year requests are rejected without
consulting labels. They cannot prove statement entailment or legal applicability
and may over-abstain on historical comparison questions. The passage gate uses
the query-fitted threshold only as a disclosed ablation; it is not calibrated.
