# Reproduce the locked temporal check

Use repository root, Python3.11 and existing uv.lock, no new dependencies/download.
The validated sample remains local at scratch/ai-v2/validated-final/account-sample.csv.
Its SHA256 and all six computational source hashes are enforced by reserve-lock.json.
Existing outputs must be preserved; commands below illustrate a NEW output directory
for an explicit independent reproduction, not instructions to repeat the recorded run.

```sh
mkdir -p scratch/ai-v4/reproduction
PYTHONPATH=src UV_NO_SYNC=1 UV_PYTHON=3.11 uv run --frozen --no-sync python -m meridian.evaluation.external.temporal extract scratch/ai-v2/validated-final/account-sample.csv docs/evaluation/v4/final/reserve-lock.json scratch/ai-v4/reproduction/features.jsonl
PYTHONPATH=src UV_NO_SYNC=1 UV_PYTHON=3.11 uv run --frozen --no-sync python -m meridian.evaluation.external.temporal evaluate scratch/ai-v4/reproduction/features.jsonl docs/evaluation/v4/final/reserve-lock.json scratch/ai-v4/reproduction/results.json
```

Extraction/evaluation refuse existing outputs; receipts bind cache/sample/lock.
Compare metrics and feature hashes, not wall time or RSS. Original features/results
started receipts and final results are archived alongside this document. The exact
source-audit.py was executed against the original scratch/ai-v4/reserve cache and
writes source-audit.json; its recorded hash matches the archived script. It does
not change source data or feature cache. Run with PYTHONPATH=src and locked Python.

Final integration command and environment are in verification.json; use the
existing guarded loopback55432 meridian_test role URLs from v2 reproduction
instructions. Never substitute the demo database. integration.log preserves
actual stdout. Source hashes in verification.json bind the tested code and tests;
subsequent edits in this closure are documentation/receipt archiving only.
