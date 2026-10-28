# Reproduce Stage 4

Python 3.11, existing locked dependencies; no download or new dependency needed.
Use the existing validated IBM sample, whose SHA256 is checked before extraction.
All outputs below must be new paths. Preserve caches and receipts rather than
rerunning extraction unnecessarily. Do not edit the frozen protocol or source
code and then describe old outputs as measurements of the changed definitions.

```sh
PYTHONPATH=src UV_NO_SYNC=1 UV_PYTHON=3.11 uv run --frozen --no-sync python \
  -m meridian.evaluation.external.intelligence_eval extract \
  scratch/ai-v2/validated-final/account-sample.csv \
  docs/evaluation/v4/PROTOCOL.md scratch/ai-v4/features.jsonl
PYTHONPATH=src UV_NO_SYNC=1 UV_PYTHON=3.11 uv run --frozen --no-sync python \
  -m meridian.evaluation.external.intelligence_eval evaluate \
  scratch/ai-v4/features.jsonl docs/evaluation/v4/PROTOCOL.md \
  scratch/ai-v4/results.json
```

The cache receipt binds sample, protocol, feature and runner hashes. Evaluation
refuses mismatches and existing output files. The runner accepts only the fixed
DEV window; it cannot silently run original HELDOUT or the reserved period.
It uses the full sample graph for the existing partition assignment but computes
features and metrics only for DEV targets and their earlier history. Evidence
row IDs and intermediate denominators are in the local feature cache.

Targeted tests:
`uv run --frozen --no-sync pytest --offline-unit-tests -q tests/test_external_intelligence.py tests/test_external_financial.py tests/test_capacity_audit.py`

For integration, use the existing guarded loopback disposable-database role URLs
from v2 reproduction instructions. The executed checkpoint selected those first
two test files plus test_amount_deviation.py, test_transaction_velocity.py,
test_graph_structure_signals.py, test_risk_scoring.py and test_test_guard.py.
Do not run migrations against the demo database.

`capacity.tie_bounds` consumes cached source_row/score/label records and the
fixed budget 278. Its post-measurement tie diagnostic does not tune features or
change rankings; `tie-sensitivity.json` reports possible ordering bounds.
Historical evaluation metrics and the reserved period remain unchanged.
