import json
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine

from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
    compute_amount_deviation,
)
from meridian.fixtures.generator import FIXTURE_VERSION, GENERATOR_VERSION
from meridian.risk_engine.risk_signals import compute_risk_score


def _canonical_serializer(obj: Any) -> str:
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, uuid.UUID):
        return str(obj)
    # Task 1 didn't use datetime in manifest output, but we use it safely if needed.
    return str(obj)


def canonical_json(data: dict[str, Any]) -> str:
    """Canonical deterministic serialization."""
    return (
        json.dumps(
            data,
            sort_keys=True,
            separators=(",", ":"),
            default=_canonical_serializer,
        )
        + "\n"
    )


def _compute_median(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / Decimal("2.0")


def compute_roc_auc(
    positives: list[Decimal], negatives: list[Decimal]
) -> dict[str, Any]:
    """Pure Python ROC-AUC using Mann-Whitney U test formulation with average ranks."""
    n_pos = len(positives)
    n_neg = len(negatives)
    if n_pos == 0 or n_neg == 0:
        return {
            "auc": None,
            "n_positive": n_pos,
            "n_negative": n_neg,
            "reason": "missing positive or negative class observations",
        }

    # Assign ranks with ties
    all_vals = [(val, 1) for val in positives] + [(val, 0) for val in negatives]
    all_vals.sort(key=lambda x: x[0])

    ranks: dict[Decimal, float] = {}
    i = 0
    while i < len(all_vals):
        val = all_vals[i][0]
        start_idx = i
        while i < len(all_vals) and all_vals[i][0] == val:
            i += 1
        count = i - start_idx
        avg_rank = sum(range(start_idx + 1, i + 1)) / count
        ranks[val] = avg_rank

    sum_ranks_pos = sum(ranks[v] for v in positives)
    u_pos = sum_ranks_pos - (n_pos * (n_pos + 1)) / 2.0
    auc = u_pos / (n_pos * n_neg)

    return {
        "auc": float(auc),
        "n_positive": n_pos,
        "n_negative": n_neg,
    }


def measure_baseline(
    engine: Engine, fixtures_manifest: dict[str, Any]
) -> dict[str, Any]:
    """
    Measures the existing PROTOTYPE amount_deviation signal
    against the Task 1 fixture corpus.
    """
    fixtures = fixtures_manifest["fixtures"]
    seed = fixtures_manifest.get("seed", "unknown")

    # Exclusions
    excluded_counts: dict[str, int] = defaultdict(int)
    eligible_fixtures = []

    for fx in fixtures:
        sc = fx.get("scenario_class")
        if sc == "worked_example":
            excluded_counts["worked_example"] += 1
            continue
        if sc == "insufficient_history":
            excluded_counts["runtime_edge_case"] += 1
            continue
        if not fx.get("alert_spec", {}).get("transaction_id"):
            excluded_counts["missing_transaction_id"] += 1
            continue

        eligible_fixtures.append(fx)

    results_by_split: dict[str, dict[str, list[Decimal]]] = {
        "train": {"pos": [], "neg": []},
        "eval": {"pos": [], "neg": []},
        "pooled": {"pos": [], "neg": []},
    }

    stats_by_scenario: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "n_computed": 0, "n_unknown": 0, "values": []}
    )

    for fx in eligible_fixtures:
        tx_id_str = fx["alert_spec"]["transaction_id"]
        tx_id = uuid.UUID(tx_id_str)
        gt = fx["ground_truth"]
        is_pos = gt != "CLEAN"
        split = fx.get("split", "eval")
        sc = fx["scenario_class"]

        stats_by_scenario[sc]["n"] += 1

        result = compute_amount_deviation(engine, tx_id)
        if isinstance(result, AmountDeviationComputed):
            score_result = compute_risk_score(result)
            val = score_result.value

            stats_by_scenario[sc]["n_computed"] += 1
            stats_by_scenario[sc]["values"].append(val)

            cls_key = "pos" if is_pos else "neg"
            results_by_split[split][cls_key].append(val)
            results_by_split["pooled"][cls_key].append(val)
        elif isinstance(result, AmountDeviationUnknown):
            stats_by_scenario[sc]["n_unknown"] += 1
        else:
            stats_by_scenario[sc]["n_unknown"] += 1

    # Format scenario stats
    scenario_reports = {}
    for sc, stats in stats_by_scenario.items():
        vals = stats["values"]
        min_val = str(min(vals)) if vals else None
        max_val = str(max(vals)) if vals else None
        median_val = _compute_median(vals)
        median_str = str(median_val) if median_val is not None else None

        scenario_reports[sc] = {
            "n": stats["n"],
            "n_computed": stats["n_computed"],
            "n_unknown": stats["n_unknown"],
            "min": min_val,
            "median": median_str,
            "max": max_val,
        }

    # Format AUCs
    aucs = {}
    for split_name, data in results_by_split.items():
        if split_name != "pooled" and (not data["pos"] and not data["neg"]):
            continue
        aucs[split_name] = compute_roc_auc(data["pos"], data["neg"])

    # Output contract
    report = {
        "metadata": {
            "fixture_version": FIXTURE_VERSION,
            "generator_version": GENERATOR_VERSION,
            "seed": seed,
            "split_methodology": "md5(seed_fix_id) % 2 even=train odd=eval",
            "methodology_tier": "PROTOTYPE",
            "explicit_disclaimer": (
                "No threshold was selected. No calibration was performed. "
                "No risk-level mapping was derived. The amount-deviation "
                "implementation was unchanged. The dataset is synthetic. "
                "Small sample size limits inference."
            ),
        },
        "exclusions": dict(excluded_counts),
        "per_scenario_statistics": scenario_reports,
        "auc_results": aucs,
    }

    return report


if __name__ == "__main__":
    import os
    import sys

    from sqlalchemy import create_engine

    from meridian.fixtures.generator import generate_fixtures

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(db_url)
    # The evaluation fixture corpus is assumed to already exist in the database.
    # We still need the manifest to know which transactions to process.
    res = generate_fixtures("baseline_seed")

    report = measure_baseline(engine, res["manifest"])
    print(canonical_json(report), end="")
