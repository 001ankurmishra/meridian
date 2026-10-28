# AI upgrade v2 — external data intake

Historical first-slice status at d40e910. Current measured intake, corpus and baseline
results are in `baseline-report.md`; native customer/full-graph evaluation remains
incomplete. The remaining-work list below records the original intake checkpoint.
Started 2026-10-26 from merged main `af924e539aa228ce3307b9d1fd949c67b261222f`.

## Financial source

Publisher: [IBM AML-Data](https://github.com/IBM/AML-Data).
The repository's Apache-2.0 license does not license the transaction data.
Data uses [CDLA-Sharing-1.0](https://cdla.dev/sharing-1-0/): retain attribution
and license on redistribution; identify modifications and license enhanced data
under those terms. This project does not redistribute the raw archive.

The publisher-linked Kaggle listing/download attempts returned HTTP 404 on
2026-10-26. The publisher's [original Box archive](https://ibm.box.com/v/AML-Anti-Money-Laundering-Data)
remains accessible. Selected version: **Dataset A, February 2021**, explicitly
older than the improved 2023 release. Do not label it HI-Small or the current
Kaggle dataset. Box file ID 780504045395, `trans_3000p2_list.txt.bz2`.

[Publisher documentation](https://ibm.box.com/v/AML-Anti-Money-Laundering-Data/file/780515045707)
dated February 25, 2021 reports 839,740,068 compressed bytes, 4,532,100,611
uncompressed bytes, 45,351,509 negative and 55,423 positive transactions.
Those are **publisher counts, not locally verified counts** until full validation.
Its labels track simulated illicit-origin funds, including subsequent transfers;
they are not suspicious-activity or regulatory determinations. The documentation
describes January 2019 activity. Timezone, KYC, customer-to-account ownership and
scenario membership are not supplied in the CSV; do not invent them.

## Reproduction and isolation

Use Python 3.11 and the committed lock/development environment:

```sh
PYTHONPATH=src .venv/bin/python -m meridian.evaluation.external.download_ibm scratch/ai-v2/ibm-original
uv run --frozen --no-sync pytest --offline-unit-tests -q tests/test_external_ibm.py tests/test_external_download.py
```

`scratch/` is excluded from both Git and Docker contexts. Downloader checks the
documented byte size and bzip2 signature, writes through an exclusive partial
file, and emits a dated SHA256 receipt. The locally observed digest is not a
publisher signature. Full decompression, row counting, currency/payment-format
inventory, duplicate accounting and checksum pinning remain required.

The streaming reader checks the exact positional header, finite nonnegative
decimal amounts, timestamps, nonblank currency/format fields, identifiers and
binary generator labels. It preserves separate sender/receiver accounts despite
duplicate column names, duplicate records, source row numbers, original currency
names and unspecified timezone. No application or demo database is accessed.
Parser tests use explicitly hand-authored controls, never external benchmark labels.

## Reference corpus research

Official-source candidates are being evaluated before ingestion. The
[BIS terms](https://www.bis.org/about/terms-conditions) allow noncommercial
redistribution and bounded attributed extracts. The
[FATF terms](https://www.fatf-gafi.org/en/pages/terms-conditions.html) describe
attribution and integrity requirements; individual publication notices must also
be checked. RBI source permissions and document currency remain unverified.
No external reference content is yet ingested or represented as bank policy.

## Remaining milestone gates

1. Complete archive validation and provenance receipt; define a reproducible,
   representative evaluation subset with duplicates and uncertainty accounted for.
2. Verify reference-document identities, permissions, versions and applicability;
   implement deterministic provenance-preserving chunking in isolated artifacts.
3. Define and freeze v2 financial/retrieval splits and labels before measurement.
   Account/graph leakage and missing ownership/scenario metadata need explicit
   treatment; chronological row order cannot be assumed.
4. Measure baseline usefulness, uncertainty, failure cases and resource use.

Frozen v1 retrieval artifacts and accepted runtime behavior remain unchanged.
No model replacement, paid API call, data transmission to an LLM, push or merge
is authorized by this intake implementation.
