"""Cached DEV-only financial experiments on the existing validated IBM sample."""

import argparse
import csv
import hashlib
import json
import math
import platform
import random
import resource
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from meridian.evaluation.external.financial import (
    Components,
    component_split,
    ranking_metrics,
)
from meridian.evaluation.external.ibm import parse_row, sha256_file
from meridian.evaluation.external.intelligence import (
    FEATURES,
    features,
    receiver,
    sender,
)

SAMPLE_SHA = "f83babca4a2c3d99f6e0f411819b78eed6f59557a3e25c426ed3bc2a890860a8"
LOWER, UPPER = datetime(2019, 1, 10), datetime(2019, 1, 17)


def fixed_budget(rows: list[dict[str, Any]]) -> dict[str, Any]:
    budget = math.ceil(len(rows) * 0.01)
    known = sorted(
        (r for r in rows if r["score"] is not None),
        key=lambda r: (-r["score"], r["source_row"]),
    )
    selected = known[:budget]
    tp = sum(r["label"] for r in selected)
    positive = sum(r["label"] for r in rows)
    return dict(
        budget=budget,
        reviewed=len(selected),
        tp=tp,
        fp=len(selected) - tp,
        recall_all_positives=tp / positive if positive else None,
        precision=tp / len(selected) if selected else None,
        tied_at_cutoff=sum(r["score"] == selected[-1]["score"] for r in known)
        if selected
        else 0,
    )


def intervals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["component"]].append(r)
    positive_groups = sum(
        any(r["label"] and r["score"] is not None for r in g) for g in groups.values()
    )
    if positive_groups < 2 or len(groups) < 10:
        return dict(status="NOT_ESTIMABLE", positive_components=positive_groups)
    rng = random.Random(20261027)
    keys = sorted(groups)
    samples: dict[str, list[float]] = defaultdict(list)
    for _ in range(200):
        replicate = [r for k in rng.choices(keys, k=len(keys)) for r in groups[k]]
        m = ranking_metrics(replicate)
        f = fixed_budget(replicate)
        for name, value in [
            ("roc_auc", m["roc_auc"]),
            ("average_precision", m["average_precision"]),
            ("precision_fixed_budget", f["precision"]),
            ("recall_all_positives", f["recall_all_positives"]),
        ]:
            if value is not None:
                samples[name].append(value)
    return dict(
        status="CONDITIONAL_OBSERVED_COMPONENT_BOOTSTRAP",
        positive_components=positive_groups,
        components=len(keys),
        intervals={
            name: dict(
                valid=len(values),
                percentile_95=[
                    sorted(values)[int(0.025 * (len(values) - 1))],
                    sorted(values)[int(0.975 * (len(values) - 1))],
                ],
            )
            for name, values in samples.items()
        },
    )


def extract(sample: Path, protocol: Path, cache: Path) -> dict[str, Any]:
    if cache.exists() or cache.with_suffix(".receipt.json").exists():
        raise FileExistsError("Feature cache already exists; use evaluation mode")
    if sha256_file(sample) != SAMPLE_SHA:
        raise ValueError("Validated sample checksum mismatch")
    start = time.monotonic()
    components = Components()
    accounts: dict[Any, list[Any]] = defaultdict(list)
    with sample.open(newline="") as stream:
        reader = csv.reader(stream)
        next(reader)
        for row in reader:
            tx = parse_row(row[3:], int(row[0]), allow_signed=True)
            left, right = sender(tx), receiver(tx)
            components.join(left, right)
            if tx.timestamp >= UPPER:
                # Later events contribute partition edges only.
                continue
            if row[1] == "1":
                accounts[left].append(tx)
            if row[2] == "1" and (right != left or row[1] != "1"):
                accounts[right].append(tx)
    receipt: dict[str, Any] = dict(
        sample_sha256=SAMPLE_SHA,
        protocol_sha256=sha256_file(protocol),
        feature_code_sha256=sha256_file(Path(__file__).with_name("intelligence.py")),
        runner_sha256=sha256_file(Path(__file__)),
        scope="DEV_ONLY",
        target_window=[LOWER.isoformat(), UPPER.isoformat()],
    )
    with cache.open("x") as output:
        count = 0
        split_digest = hashlib.sha256()
        for account in sorted(accounts):
            root = components.find(account)
            if component_split(root, "meridian-ibm-2021-components-v2.0") != "DEV":
                continue
            for f in features(account, accounts[account], LOWER, UPPER):
                tx = f.pop("tx")
                f.update(
                    source_row=tx.row_number,
                    label=tx.generator_label,
                    account=account,
                    component="|".join(root),
                    currency=tx.payment_currency,
                    format=tx.payment_format,
                    timestamp=tx.timestamp.isoformat(),
                )
                output.write(json.dumps(f, separators=(",", ":")) + "\n")
                split_digest.update(f"{tx.row_number}:DEV\n".encode())
                count += 1
    receipt.update(
        target_rows=count,
        dev_target_sha256=split_digest.hexdigest(),
        cache_sha256=sha256_file(cache),
        extraction_seconds=time.monotonic() - start,
        peak_rss_bytes=int(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if platform.system() == "Darwin" else 1024)
        ),
    )
    cache.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def evaluate(cache: Path, protocol: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("Refusing to overwrite Stage 4 results")
    receipt = json.loads(cache.with_suffix(".receipt.json").read_text())
    if (
        receipt["cache_sha256"] != sha256_file(cache)
        or receipt["protocol_sha256"] != sha256_file(protocol)
        or receipt["sample_sha256"] != SAMPLE_SHA
        or receipt["feature_code_sha256"]
        != sha256_file(Path(__file__).with_name("intelligence.py"))
        or receipt["runner_sha256"] != sha256_file(Path(__file__))
        or receipt["scope"] != "DEV_ONLY"
    ):
        raise ValueError("Cache provenance mismatch")
    start = time.monotonic()
    data = [json.loads(line) for line in cache.read_text().splitlines()]
    if any(not LOWER <= datetime.fromisoformat(r["timestamp"]) < UPPER for r in data):
        raise ValueError("Non-DEV timestamp")
    rows = {
        name: [
            dict(
                source_row=r["source_row"],
                label=r["label"],
                component=r["component"],
                score=r["values"][name],
                reason=r["reasons"][name],
                currency=r["currency"],
                format=r["format"],
            )
            for r in data
        ]
        for name in FEATURES
    }
    baseline_known = {
        name: {r["source_row"] for r in rows[name] if r["score"] is not None}
        for name in ("amount", "velocity")
    }
    reports = {}
    for name, observations in rows.items():
        print("Evaluating", name, flush=True)
        common = {r["source_row"] for r in observations if r["score"] is not None}
        reports[name] = dict(
            **ranking_metrics(observations),
            fixed_budget=fixed_budget(observations),
            uncertainty=intervals(observations),
            matched_baselines={
                baseline: {
                    "baseline": ranking_metrics(
                        [
                            r
                            for r in rows[baseline]
                            if r["source_row"] in common and r["score"] is not None
                        ]
                    ),
                    "candidate": ranking_metrics(
                        [
                            r
                            for r in observations
                            if r["source_row"] in baseline_known[baseline]
                            and r["score"] is not None
                        ]
                    ),
                }
                for baseline in ("amount", "velocity")
            },
            subgroups={
                field: {
                    value: ranking_metrics(
                        [r for r in observations if r[field] == value]
                    )
                    for value in sorted({r[field] for r in observations})
                }
                for field in ("currency", "format")
            },
        )
    result = dict(
        status="MEASURED_DEV_PROTOTYPE_SIGNALS_ONLY",
        receipt=receipt,
        targets=len(data),
        positive_targets=sum(r["label"] for r in data),
        reports=reports,
        evaluation_seconds=time.monotonic() - start,
        peak_rss_bytes=int(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            * (1 if platform.system() == "Darwin" else 1024)
        ),
        limitations=(
            "Account adaptations; partial graph; synthetic labels; "
            "90d history left-censored; no composite or fitted threshold."
        ),
    )
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["extract", "evaluate"])
    p.add_argument("input", type=Path)
    p.add_argument("protocol", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    r = (
        extract(a.input, a.protocol, a.output)
        if a.mode == "extract"
        else evaluate(a.input, a.protocol, a.output)
    )
    print(json.dumps({k: v for k, v in r.items() if k != "reports"}, indent=2))
