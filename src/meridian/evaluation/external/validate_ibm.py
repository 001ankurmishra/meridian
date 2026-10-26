"""Full streaming archive validation and label-blind ego-account sampling.

Disk-partitioned SHA256 fingerprints bound duplicate-accounting memory. No rows
are deduplicated: repeated records may be legitimate distinct payments because
the publisher supplies no transaction ID. Fingerprints exclude the label so
conflicting labels on otherwise identical records are separately counted.
"""

import argparse
import bz2
import csv
import hashlib
import json
import resource
import time
from collections import Counter
from contextlib import ExitStack
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from typing import Any

from meridian.evaluation.external.ibm import HEADER, parse_row, sha256_file

SEED = "meridian-ibm-2021-v2-account-sample-1"


@lru_cache(maxsize=200000)
def anchor(bank: str, account: str) -> bool:
    digest = hashlib.sha256(f"{SEED}|{bank}|{account}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100 == 0


def validate(source: Path, destination: Path, expected_sha256: str) -> dict[str, Any]:
    start = time.monotonic()
    digest = sha256_file(source)
    if digest != expected_sha256:
        raise ValueError("Archive SHA256 mismatch")
    destination.mkdir(parents=True, exist_ok=False)
    buckets_dir = destination / "duplicate-buckets"
    buckets_dir.mkdir()
    counts: Counter[str] = Counter()
    labels: Counter[str] = Counter()
    currencies: Counter[str] = Counter()
    formats: Counter[str] = Counter()
    days: Counter[str] = Counter()
    missing_by_column: Counter[str] = Counter()
    minimum: str | None = None
    maximum: str | None = None
    previous: str | None = None
    sample = destination / "account-sample.csv"
    with ExitStack() as stack:
        buckets = [
            stack.enter_context((buckets_dir / f"{i:02x}").open("wb"))
            for i in range(256)
        ]
        stream = stack.enter_context(
            bz2.open(source, "rt", encoding="utf-8", newline="")
        )
        output = stack.enter_context(sample.open("x", encoding="utf-8", newline=""))
        writer = csv.writer(output)
        writer.writerow(["source_row", "sender_anchor", "receiver_anchor", *HEADER])
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != HEADER:
            raise ValueError("Unexpected IBM CSV header")
        for number, row in enumerate(reader, start=2):
            counts["rows"] += 1
            counts["missing_fields"] += sum(not value.strip() for value in row)
            for column, value in enumerate(row):
                if not value.strip() or value in {"(null)", "Unknown"}:
                    name = HEADER[column] if column < len(HEADER) else "EXTRA"
                    missing_by_column[str(column) + ":" + name] += 1
            try:
                tx = parse_row(row, number)
            except ValueError:
                counts["invalid_rows"] += 1
                continue
            counts["valid_rows"] += 1
            labels[row[10]] += 1
            currencies["paid:" + tx.payment_currency] += 1
            currencies["received:" + tx.receiving_currency] += 1
            formats[tx.payment_format] += 1
            days[row[0][:10]] += 1
            minimum = min(minimum, row[0]) if minimum else row[0]
            maximum = max(maximum, row[0]) if maximum else row[0]
            counts["out_of_order_transitions"] += int(
                previous is not None and row[0] < previous
            )
            previous = row[0]
            # Exact field identity, not a claim of duplicate business events.
            fingerprint = hashlib.sha256(
                json.dumps(row[:-1], separators=(",", ":")).encode()
            ).digest()
            buckets[fingerprint[0]].write(fingerprint + bytes([tx.generator_label]))
            sender = anchor(tx.sender_bank, tx.sender_account)
            receiver = anchor(tx.receiver_bank, tx.receiver_account)
            if sender or receiver:
                writer.writerow([number, int(sender), int(receiver), *row])
                counts["sample_rows"] += 1
                counts["sample_label_" + row[10]] += 1
                if sender:
                    counts["sender_anchor_rows"] += 1
                    counts["sender_anchor_label_" + row[10]] += 1
            if number % 1000000 == 0:
                print(
                    json.dumps(
                        {
                            "rows_scanned": number - 1,
                            "elapsed_seconds": round(time.monotonic() - start),
                        }
                    ),
                    flush=True,
                )
    duplicates: Counter[str] = Counter()
    for path in sorted(buckets_dir.iterdir()):
        raw = path.read_bytes()
        if len(raw) % 33:
            raise ValueError("Corrupt duplicate-accounting bucket")
        records = sorted(raw[i : i + 33] for i in range(0, len(raw), 33))
        for _, group in groupby(records, key=lambda value: value[:32]):
            group_labels = Counter(record[-1] for record in group)
            duplicates["identical_record_excess"] += sum(
                n - 1 for n in group_labels.values()
            )
            if len(group_labels) > 1:
                duplicates["conflicting_label_groups"] += 1
        path.unlink()
    buckets_dir.rmdir()
    result: dict[str, Any] = {
        "status": "VALIDATED" if not counts["invalid_rows"] else "INVALID_ROWS_PRESENT",
        "archive_sha256": digest,
        "archive_bytes": source.stat().st_size,
        "full_bzip2_decompression": "PASS",
        "counts": dict(counts),
        "labels": dict(labels),
        "duplicates": dict(duplicates),
        "duplicate_definition": (
            "SHA256 of exact CSV fields excluding label; label counted separately"
        ),
        "timestamp_min": minimum,
        "timestamp_max": maximum,
        "timezone": "UNSPECIFIED",
        "source_missing_values_by_column": dict(missing_by_column),
        "days": dict(sorted(days.items())),
        "currencies": dict(sorted(currencies.items())),
        "formats": dict(formats),
        "sampling_seed": SEED,
        "sampling_rule": "1% hash anchors; retain either-endpoint incident rows",
        "sample_sha256": sha256_file(sample),
        "runtime_seconds": time.monotonic() - start,
        "peak_rss_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "publisher_counts": {"rows": 45406932, "0": 45351509, "1": 55423},
    }
    (destination / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.source, args.destination, args.sha256), indent=2))
