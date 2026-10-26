"""Locked account-unit diagnostics; these are not native customer-level results."""

import argparse
import csv
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from typing import Any

from meridian.evaluation.external.ibm import Transaction, parse_row, sha256_file

Account = tuple[str, str]


class Components:
    def __init__(self) -> None:
        self.parents: dict[Account, Account] = {}

    def find(self, value: Account) -> Account:
        self.parents.setdefault(value, value)
        root = value
        while self.parents[root] != root:
            root = self.parents[root]
        while value != root:
            parent = self.parents[value]
            self.parents[value] = root
            value = parent
        return root

    def join(self, left: Account, right: Account) -> None:
        a, b = self.find(left), self.find(right)
        self.parents[max(a, b)] = min(a, b)


def component_split(root: Account, seed: str) -> str:
    raw = f"{seed}|{root[0]}|{root[1]}".encode()
    return "DEV" if hashlib.sha256(raw).digest()[0] % 2 == 0 else "HELDOUT"


def ranking_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    known = [r for r in rows if r["score"] is not None]
    ordered = sorted(known, key=lambda r: (-r["score"], r["source_row"]))
    positives = sum(r["label"] for r in known)
    negatives = len(known) - positives
    tp = fp = 0
    ap = 0.0
    wins = 0.0
    for _, group in groupby(ordered, key=lambda r: r["score"]):
        batch = list(group)
        p = sum(r["label"] for r in batch)
        n = len(batch) - p
        wins += p * (negatives - fp - n) + p * n / 2
        tp += p
        fp += n
        if positives:
            ap += p / positives * tp / (tp + fp)
    capacity = math.ceil(len(known) * 0.01)
    found = sum(r["label"] for r in ordered[:capacity])
    return {
        "total": len(rows),
        "known": len(known),
        "positive": positives,
        "negative": negatives,
        "unknown": len(rows) - len(known),
        "unknown_positive": sum(r["label"] for r in rows if r["score"] is None),
        "unknown_reasons": dict(
            Counter(r["reason"] for r in rows if r["score"] is None)
        ),
        "roc_auc": wins / (positives * negatives) if positives and negatives else None,
        "average_precision": ap if positives and negatives else None,
        "review_capacity": capacity,
        "precision_at_capacity": found / capacity if capacity else None,
        "recall_at_capacity": found / positives if positives else None,
        "tp": found,
        "fp": capacity - found,
        "fn": positives - found,
        "tn": negatives - (capacity - found),
    }


def uncertainty(rows: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["score"] is not None:
            groups[row["component"]].append(row)
    positive_groups = sum(any(r["label"] for r in g) for g in groups.values())
    base: dict[str, Any] = {
        "components": len(groups),
        "positive_components": positive_groups,
    }
    if len(groups) < 10 or positive_groups < 2:
        return {
            **base,
            "status": "NOT_ESTIMABLE",
            "reason": "Too few independent observed components / positive components",
        }
    rng = random.Random(seed)
    keys = sorted(groups)
    aucs, aps = [], []
    for _ in range(200):
        replicate = [r for k in rng.choices(keys, k=len(keys)) for r in groups[k]]
        metrics = ranking_metrics(replicate)
        if metrics["roc_auc"] is not None:
            aucs.append(metrics["roc_auc"])
            aps.append(metrics["average_precision"])
    if len(aucs) < 100:
        return {**base, "status": "NOT_ESTIMABLE", "valid_replicates": len(aucs)}

    def interval(values: list[float]) -> list[float]:
        values.sort()
        return [
            values[int(0.025 * (len(values) - 1))],
            values[int(0.975 * (len(values) - 1))],
        ]

    return {
        **base,
        "status": "CONDITIONAL_COMPONENT_BOOTSTRAP",
        "valid_replicates": len(aucs),
        "roc_auc_95": interval(aucs),
        "average_precision_95": interval(aps),
    }


def account_features(transactions: list[Transaction]) -> list[dict[str, Any]]:
    ordered = sorted(transactions, key=lambda tx: (tx.timestamp, tx.row_number))
    history: deque[Transaction] = deque()
    day: deque[Transaction] = deque()
    currency_counts: Counter[str] = Counter()
    amount_sum = Decimal(0)
    missing = 0
    negative = 0
    day_unsupported = 0
    result = []
    for timestamp, group in groupby(ordered, key=lambda tx: tx.timestamp):
        batch = list(group)
        while history and history[0].timestamp < timestamp - timedelta(days=90):
            tx = history.popleft()
            currency_counts[tx.payment_currency] -= 1
            if not currency_counts[tx.payment_currency]:
                del currency_counts[tx.payment_currency]
            if tx.paid is None:
                missing -= 1
            else:
                amount_sum -= tx.paid
                negative -= int(tx.paid < 0)
        while day and day[0].timestamp < timestamp - timedelta(hours=24):
            expired = day.popleft()
            day_unsupported -= int(expired.paid is None or expired.paid < 0)
        batch_unsupported = sum(tx.paid is None or tx.paid < 0 for tx in batch)
        for tx in batch:
            reason = None
            if negative or (tx.paid is not None and tx.paid < 0):
                reason = "UNSUPPORTED_SIGNED_AMOUNT"
            elif tx.paid is None or missing or tx.payment_currency == "Unknown":
                reason = "MISSING_AMOUNT_OR_CURRENCY"
            elif not history:
                reason = "NO_HISTORY"
            elif set(currency_counts) != {tx.payment_currency}:
                reason = "CURRENCY_MISMATCH"
            elif amount_sum == 0:
                reason = "ZERO_AVERAGE"
            result.append(
                {
                    "tx": tx,
                    "velocity": (
                        None
                        if day_unsupported or batch_unsupported
                        else len(day) + len(batch)
                    ),
                    "amount": (
                        float(tx.paid / (amount_sum / len(history)))
                        if reason is None and tx.paid is not None
                        else None
                    ),
                    "amount_reason": reason,
                }
            )
        # Amount history excludes all equal-timestamp events.
        for tx in batch:
            history.append(tx)
            day.append(tx)
            day_unsupported += int(tx.paid is None or tx.paid < 0)
            currency_counts[tx.payment_currency] += 1
            if tx.paid is None:
                missing += 1
            else:
                amount_sum += tx.paid
                negative += int(tx.paid < 0)
    return result


def evaluate(sample: Path, protocol_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("Refusing to overwrite financial evaluation")
    start = time.monotonic()
    protocol = json.loads(protocol_path.read_text())
    validation = json.loads(sample.with_name("validation.json").read_text())
    if (
        validation["status"] != "VALIDATED"
        or validation["archive_sha256"] != protocol["dataset_sha256"]
        or sha256_file(sample) != validation["sample_sha256"]
    ):
        raise ValueError("Financial input validation mismatch")
    components = Components()
    accounts: dict[Account, list[Transaction]] = defaultdict(list)
    first_edge: dict[tuple[Account, Account], datetime] = {}
    with sample.open(newline="") as stream:
        reader = csv.reader(stream)
        next(reader)
        for row in reader:
            tx = parse_row(row[3:], int(row[0]), allow_signed=True)
            left = (tx.sender_bank, tx.sender_account)
            right = (tx.receiver_bank, tx.receiver_account)
            components.join(left, right)
            edge = (left, right)
            if tx.paid is not None and tx.paid >= 0:
                first_edge[edge] = min(first_edge.get(edge, tx.timestamp), tx.timestamp)
            if row[1] == "1":
                accounts[left].append(tx)
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    split_digest = hashlib.sha256()
    split_counts: Counter[str] = Counter()
    cycle_counts: Counter[str] = Counter()
    component_sizes: Counter[Account] = Counter()
    for node in components.parents:
        component_sizes[components.find(node)] += 1
    for account in sorted(accounts):
        root = components.find(account)
        split = component_split(root, protocol["split_seed"])
        bounds = protocol[
            "dev_target_window" if split == "DEV" else "heldout_target_window"
        ]
        lower, upper = map(datetime.fromisoformat, bounds)
        for feature in account_features(accounts[account]):
            tx = feature["tx"]
            if not lower <= tx.timestamp < upper:
                continue
            split_digest.update(f"{tx.row_number}:{split}\n".encode())
            split_counts[split] += 1
            reverse = first_edge.get(((tx.receiver_bank, tx.receiver_account), account))
            witnessed = (
                account != (tx.receiver_bank, tx.receiver_account)
                and tx.paid is not None
                and tx.paid >= 0
                and reverse is not None
                and reverse <= tx.timestamp
            )
            cycle_counts[
                split
                + (":RECIPROCAL_WITNESS" if witnessed else ":UNKNOWN_LONGER_PATHS")
            ] += 1
            for name in ("velocity", "amount"):
                rows[split + ":" + name].append(
                    {
                        "source_row": tx.row_number,
                        "label": tx.generator_label,
                        "component": "|".join(root),
                        "score": feature[name],
                        "reason": feature["amount_reason"]
                        if name == "amount"
                        else "UNSUPPORTED_OR_MISSING_AMOUNT_IN_24H"
                        if feature["velocity"] is None
                        else None,
                        "currency": tx.payment_currency,
                        "format": tx.payment_format,
                    }
                )
    reports = {}
    for name, observations in sorted(rows.items()):
        reports[name] = {
            **ranking_metrics(observations),
            "uncertainty": uncertainty(observations, protocol["bootstrap_seed"]),
            "subgroups": {
                field: {
                    value: ranking_metrics(
                        [r for r in observations if r[field] == value]
                    )
                    for value in sorted({r[field] for r in observations})
                }
                for field in ("currency", "format")
            },
        }
    result = {
        "status": "MEASURED_ACCOUNT_ADAPTATIONS_ONLY",
        "native_compatibility": protocol["native_compatibility"],
        "protocol_sha256": sha256_file(protocol_path),
        "sample_sha256": sha256_file(sample),
        "split_sha256": split_digest.hexdigest(),
        "target_rows": dict(split_counts),
        "observed_nodes": len(components.parents),
        "observed_components": len(component_sizes),
        "largest_component_nodes": max(component_sizes.values(), default=0),
        "sampled_anchor_accounts": len(accounts),
        "reports": reports,
        "graph_coverage": dict(cycle_counts),
        "leakage_limitations": protocol["leakage_limits"],
        "runtime_seconds": time.monotonic() - start,
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sample", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = evaluate(args.sample, args.protocol, args.output)
    print(json.dumps({k: v for k, v in result.items() if k != "reports"}, indent=2))
