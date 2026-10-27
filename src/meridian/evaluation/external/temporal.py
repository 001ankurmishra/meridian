"""One locked temporal check; preserves all earlier DEV and HELDOUT artifacts."""

import argparse
import csv
import json
import platform
import random
import resource
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta
from itertools import groupby
from pathlib import Path
from typing import Any

from meridian.evaluation.external.capacity import tie_bounds
from meridian.evaluation.external.financial import (
    Account,
    Components,
    account_features,
    component_split,
    ranking_metrics,
)
from meridian.evaluation.external.ibm import Transaction, parse_row, sha256_file
from meridian.evaluation.external.intelligence import receiver, sender
from meridian.evaluation.external.intelligence_eval import SAMPLE_SHA

SELECTED = ("amount", "velocity", "relative_velocity", "reciprocal_24h", "fan_in_24h")
LOWER, UPPER = datetime(2019, 1, 17), datetime(2019, 1, 24)
BUDGET = 278


def selected_features(
    account: Account, events: list[Transaction]
) -> list[dict[str, Any]]:
    """Same frozen formulas, without computing the five unselected candidates."""
    ordered = sorted(
        (t for t in events if t.timestamp < UPPER),
        key=lambda t: (t.timestamp, t.row_number),
    )
    baseline = {
        f["tx"].row_number: f
        for f in account_features([t for t in ordered if sender(t) == account])
    }
    prior: deque[Transaction] = deque()
    incoming: deque[Transaction] = deque()
    result = []
    for timestamp, g in groupby(ordered, key=lambda t: t.timestamp):
        batch = list(g)
        out = [t for t in batch if sender(t) == account]
        while prior and prior[0].timestamp < timestamp - timedelta(days=8):
            prior.popleft()
        while incoming and incoming[0].timestamp < timestamp - timedelta(hours=24):
            incoming.popleft()
        if timestamp >= LOWER:
            week = [t for t in prior if t.timestamp < timestamp - timedelta(days=1)]
            invalid_in = any(
                t.received is None or t.received < 0 or t.paid is None or t.paid < 0
                for t in incoming
            )
            for tx in out:
                b = baseline[tx.row_number]
                scores: dict[str, float | None] = {name: None for name in SELECTED}
                reasons: dict[str, Any] = {name: None for name in SELECTED}
                scores.update(amount=b["amount"], velocity=b["velocity"])
                reasons.update(
                    amount=b["amount_reason"],
                    velocity=(
                        "UNSUPPORTED_OR_MISSING_AMOUNT_IN_24H"
                        if b["velocity"] is None
                        else None
                    ),
                )
                if b["velocity"] is None or any(
                    t.paid is None or t.paid < 0 for t in week
                ):
                    reasons["relative_velocity"] = "UNSUPPORTED_OR_MISSING_DIRECTION"
                elif not week:
                    reasons["relative_velocity"] = "ZERO_PRIOR_WEEK_COUNT"
                else:
                    scores["relative_velocity"] = float(b["velocity"] * 7 / len(week))
                for name in ("reciprocal_24h", "fan_in_24h"):
                    if receiver(tx) == account:
                        reasons[name] = "TARGET_SELF_TRANSFER"
                    elif tx.paid is None or tx.paid < 0 or invalid_in:
                        reasons[name] = "UNSUPPORTED_OR_MISSING_DIRECTION"
                    elif name == "reciprocal_24h":
                        scores[name] = float(
                            any(sender(t) == receiver(tx) for t in incoming)
                        )
                    else:
                        scores[name] = float(len({sender(t) for t in incoming}))
                # Source row IDs reconstruct full amount history from the sample;
                # keep explicit local temporal witnesses for graph/relative count.
                result.append(
                    dict(
                        tx=tx,
                        values=scores,
                        reasons=reasons,
                        evidence=dict(
                            prior_week_rows=[t.row_number for t in week],
                            prior_24h_incoming_rows=[t.row_number for t in incoming],
                            current_24h_outgoing_rows=[
                                t.row_number
                                for t in prior
                                if t.timestamp >= timestamp - timedelta(days=1)
                            ]
                            + [t.row_number for t in out],
                        ),
                        amount_history_query=dict(
                            account=account,
                            start=(timestamp - timedelta(days=90)).isoformat(),
                            end_exclusive=timestamp.isoformat(),
                        ),
                    )
                )
        prior.extend(out)
        incoming.extend(
            t for t in batch if receiver(t) == account and sender(t) != account
        )
    return result


def evidence_key(lock_hash: str, account: Account, source_row: int, name: str) -> str:
    return str(
        uuid.uuid5(
            uuid.NAMESPACE_URL,
            json.dumps([SAMPLE_SHA, lock_hash, account, source_row, name]),
        )
    )


def validate_lock(path: Path) -> dict[str, Any]:
    lock: dict[str, Any] = json.loads(path.read_text())
    if (
        lock["selected"] != list(SELECTED)
        or lock["budget"] != BUDGET
        or lock["window"] != [LOWER.isoformat(), UPPER.isoformat()]
        or lock["sample_sha256"] != SAMPLE_SHA
        or lock["status"] != "LOCKED_BEFORE_RESERVE"
    ):
        raise ValueError("Temporal lock definitions mismatch")
    for file, digest in lock["code_sha256"].items():
        if sha256_file(Path(file)) != digest:
            raise ValueError("Temporal code lock mismatch")
    return lock


def budget_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        (r for r in rows if r["score"] is not None),
        key=lambda r: (-r["score"], r["source_row"]),
    )[:BUDGET]
    tp = sum(r["label"] for r in ordered)
    positives = sum(r["label"] for r in rows)
    return dict(
        budget=BUDGET,
        reviewed=len(ordered),
        tp=tp,
        fp=len(ordered) - tp,
        fn_all_targets=positives - tp,
        precision=tp / len(ordered) if ordered else None,
        recall_all_positives=tp / positives if positives else None,
    )


def uncertainty(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[r["component"]].append(r)
    positives = sum(
        any(r["label"] and r["score"] is not None for r in g) for g in groups.values()
    )
    if positives < 2 or len(groups) < 10:
        return dict(status="NOT_ESTIMABLE", positive_components=positives)
    rng = random.Random(20261027)
    keys = sorted(groups)
    metrics: dict[str, list[float]] = defaultdict(list)
    for _ in range(200):
        rep = [r for k in rng.choices(keys, k=len(keys)) for r in groups[k]]
        m = ranking_metrics(rep)
        b = budget_metrics(rep)
        for key, value in [
            ("roc_auc", m["roc_auc"]),
            ("average_precision", m["average_precision"]),
            ("precision", b["precision"]),
            ("recall_all_positives", b["recall_all_positives"]),
        ]:
            if value is not None:
                metrics[key].append(value)
    return dict(
        status="CONDITIONAL_COMPONENT_BOOTSTRAP",
        positive_components=positives,
        components=len(groups),
        intervals={
            k: dict(
                valid=len(v),
                percentile_95=[
                    sorted(v)[int(0.025 * (len(v) - 1))],
                    sorted(v)[int(0.975 * (len(v) - 1))],
                ],
            )
            for k, v in metrics.items()
        },
    )


def extract(sample: Path, lock_path: Path, cache: Path) -> None:
    validate_lock(lock_path)
    if sha256_file(sample) != SAMPLE_SHA:
        raise ValueError("Sample mismatch")
    started = cache.with_suffix(".started.json")
    with started.open("x") as f:
        json.dump({"lock_sha256": sha256_file(lock_path)}, f)
    if cache.exists():
        raise FileExistsError("Existing cache")
    begin = time.monotonic()
    accounts: dict[Account, list[Transaction]] = defaultdict(list)
    components = Components()
    with sample.open(newline="") as f:
        reader = csv.reader(f)
        next(reader)
        for row in reader:
            tx = parse_row(row[3:], int(row[0]), allow_signed=True)
            left, right = sender(tx), receiver(tx)
            components.join(left, right)
            if tx.timestamp >= UPPER:
                continue
            if row[1] == "1":
                accounts[left].append(tx)
            if row[2] == "1" and (left != right or row[1] != "1"):
                accounts[right].append(tx)
    lock_hash = sha256_file(lock_path)
    count = 0
    with cache.open("x") as f:
        for account in sorted(accounts):
            root = components.find(account)
            if component_split(root, "meridian-ibm-2021-components-v2.0") != "DEV":
                continue
            for r in selected_features(account, accounts[account]):
                tx = r.pop("tx")
                r.update(
                    source_row=tx.row_number,
                    label=tx.generator_label,
                    component="|".join(root),
                    account=account,
                    timestamp=tx.timestamp.isoformat(),
                    currency=tx.payment_currency,
                    format=tx.payment_format,
                    evidence_keys={
                        name: evidence_key(lock_hash, account, tx.row_number, name)
                        for name in SELECTED
                    },
                )
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
                count += 1
    receipt = dict(
        lock_sha256=lock_hash,
        sample_sha256=SAMPLE_SHA,
        cache_sha256=sha256_file(cache),
        targets=count,
        extraction_seconds=time.monotonic() - begin,
        peak_rss_bytes=rss(),
    )
    cache.with_suffix(".receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


def rss() -> int:
    return int(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        * (1 if platform.system() == "Darwin" else 1024)
    )


def evaluate(cache: Path, lock_path: Path, output: Path) -> None:
    validate_lock(lock_path)
    receipt = json.loads(cache.with_suffix(".receipt.json").read_text())
    if receipt["lock_sha256"] != sha256_file(lock_path) or receipt[
        "cache_sha256"
    ] != sha256_file(cache):
        raise ValueError("Cache provenance mismatch")
    if output.exists():
        raise FileExistsError("Existing final result")
    with output.with_suffix(".started.json").open("x") as f:
        json.dump(receipt, f)
    begin = time.monotonic()
    data = [json.loads(s) for s in cache.read_text().splitlines()]
    if any(not LOWER <= datetime.fromisoformat(r["timestamp"]) < UPPER for r in data):
        raise ValueError("Outside locked temporal window")
    rows = {
        name: [
            dict(
                source_row=r["source_row"],
                label=r["label"],
                score=r["values"][name],
                reason=r["reasons"][name],
                component=r["component"],
            )
            for r in data
        ]
        for name in SELECTED
    }
    reports = {}
    for name, obs in rows.items():
        print("Measuring locked reserve", name, flush=True)
        paired = {}
        for base in ("amount", "velocity"):
            common = {r["source_row"] for r in obs if r["score"] is not None} & {
                r["source_row"] for r in rows[base] if r["score"] is not None
            }
            paired[base] = {
                side: dict(
                    **ranking_metrics([r for r in items if r["source_row"] in common]),
                    fixed_budget=budget_metrics(
                        [r for r in items if r["source_row"] in common]
                    ),
                )
                for side, items in [("candidate", obs), ("baseline", rows[base])]
            }
        reports[name] = dict(
            **ranking_metrics(obs),
            fixed_budget=budget_metrics(obs),
            ties=tie_bounds(obs, BUDGET),
            uncertainty=uncertainty(obs),
            common_cohorts=paired,
        )
    result = dict(
        status="LOCKED_TEMPORAL_CHECK_NOT_INDEPENDENT_CUSTOMER_VALIDATION",
        receipt=receipt,
        targets=len(data),
        positive_targets=sum(r["label"] for r in data),
        reports=reports,
        evaluation_seconds=time.monotonic() - begin,
        peak_rss_bytes=rss(),
    )
    output.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["extract", "evaluate"])
    p.add_argument("input", type=Path)
    p.add_argument("lock", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    if a.mode == "extract":
        extract(a.input, a.lock, a.output)
    else:
        evaluate(a.input, a.lock, a.output)
