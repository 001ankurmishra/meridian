# Reproducing the v2 intake and baseline

Use the committed lock with Python 3.11 and the development dependencies.
Do not use these commands against a demo/production database. No external LLM is
called. Do not rerun v1 HELDOUT, replace frozen results, or tune on v2 HELDOUT.

## Archive intake

```sh
uv sync --frozen --all-groups --python 3.11
PYTHONPATH=src .venv/bin/python -m meridian.evaluation.external.download_ibm scratch/ai-v2/ibm-original
PYTHONPATH=src .venv/bin/python -m meridian.evaluation.external.validate_ibm \
  scratch/ai-v2/ibm-original/trans_3000p2_list.txt.bz2 \
  scratch/ai-v2/validated-final \
  --sha256 b58b23154907e95e27a23ec95775cdfaf65ae846d3d4717c611c7d8a45dc8299
```

The downloader refuses to overwrite an existing archive. Reuse the verified file
instead of invoking it again. Validation requires a new destination, reads the
entire archive, verifies bzip2 integrity and SHA256, counts every source record,
and builds the label-blind sample plus disk-partitioned duplicate fingerprints.
It retains publisher `(null)` amounts as unknown and signed amounts as supplied;
the financial adapters do not turn unsupported signed values into normal flows.
The validator's `VALIDATED` status means source-format integrity, not suitability
of every row for every signal. Missing/signed amounts remain limitations.

The 1% anchor selection retains every incident record, not 1% of individual
transactions. Only outgoing anchor transactions become scoring targets. Incoming
and other incident records preserve observed relationships. Original row numbers
identify source records; no customer identity or scenario labels are invented.

## Financial diagnostics

```sh
PYTHONPATH=src .venv/bin/python -m meridian.evaluation.external.financial \
  scratch/ai-v2/validated-final/account-sample.csv \
  docs/evaluation/v2/financial-protocol-v2.1.json \
  scratch/ai-v2/financial-baseline.json
```

The protocol and implementation were committed before metrics were computed.
Version 2.1 records the signed-amount treatment discovered during intake; v2.0
remains preserved. No sampling seed, split, signal direction or ranking metric was
selected using performance. Component splits preserve observed graph separation;
hidden ownership and omitted unsampled-node edges prevent a full-source/customer
independence claim. Account formulas are explicitly **adaptations**, not direct
tests of native customer-level SQL. No classifier, composite score or calibrated
threshold is fitted. Amount-history results are January-window diagnostics with
left censoring relative to 90 days. Unknowns are not imputed.

## Public references

For local noncommercial research under the source terms:

```sh
HF_HUB_OFFLINE=1 PYTHONPATH=src .venv/bin/python -m meridian.evaluation.external.references \
  docs/evaluation/v2/reference-sources.json scratch/ai-v2/references \
  scratch/ai-v2/references/chunks-v2.jsonl --download
```

This verifies the pinned PDF digests and reuses matching local files. The
development-only PDF parser is pinned in the lock. BGE's already-pinned tokenizer
is used offline; its existing cache is required. All chunks retain PDF page,
source, version, copyright and external-reference metadata, and no chunk is
represented as bank policy. The approved corpus SHA256 is
`2dedab9e14bc868c6e861b86b3bb5c09fae9e4897d6fa6168cec7c5c1393ffa0`.
Ingestion was independently repeated locally and produced the same bytes/hash.
Full text, PDFs, samples and caches stay under ignored `scratch/`.

## Retrieval baseline

The committed result is the original approved measurement; use it for subsequent
analysis. The following explains reproduction in a fresh disposable environment,
not authorization to repeatedly run or retune HELDOUT:

1. Start `docker-compose.test.yml` and configure the maintenance/application/loader
   test URLs described in `docs/TESTING.md`; apply fresh test migrations under the
   existing disposable-database guard if necessary.
2. Set `HF_HUB_OFFLINE=1`, `UV_NO_SYNC=1`, `UV_PYTHON=3.11`.
3. Run:

```sh
PYTHONPATH=src .venv/bin/python -m meridian.evaluation.external.retrieval \
  docs/evaluation/v2 scratch/ai-v2/references/chunks-v2.jsonl \
  scratch/ai-v2/retrieval-baseline.json
```

The command validates the explicit maintainer freeze and corpus digest before
evaluation, then uses the application role's TEMP privilege. Temporary tables
shadow `documents` and `document_chunks` for one connection and are dropped at
transaction end. No public-table contents, runtime corpus or production permissions
are changed. Actual native `retrieve_policy_evidence` supplies unchanged BGE,
complete lexical/semantic rankings, RRF and ADR-0009's gate.

The result and started receipt prevent accidental overwrite of that run. Any
interrupted run requires inspection, not deletion of its receipt to bypass the
guard. New candidate experiments need separately recorded configurations and
must not tune against the already measured heldout results.
