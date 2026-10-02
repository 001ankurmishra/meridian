import math
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
from meridian.agents.transaction.beneficiary_age import (
    BeneficiaryAgeComputed,
    BeneficiaryAgeUnknown,
    compute_beneficiary_age,
)
from meridian.agents.transaction.transaction_velocity import (
    compute_transaction_velocity,
)
from meridian.fixtures.amount_deviation_baseline import (
    canonical_json,
    compute_roc_auc,
)
from meridian.risk_engine.risk_signals import compute_risk_score

# F3 wordings
AMOUNT_DEVIATION_DIRECTION = "HIGHER"  # HIGHER = more suspicious
TRANSACTION_VELOCITY_DIRECTION = "HIGHER"  # HIGHER = more suspicious
BENEFICIARY_AGE_DIRECTION = "LOWER"  # LOWER age = more suspicious


def _compute_median(values: list[Decimal]) -> Decimal | None:
    # Intentional duplication from amount_deviation_baseline.py to avoid
    # importing private helpers
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / Decimal("2.0")


def compute_hanley_mcneil_se(auc: float, n1: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 0.0
    A = auc
    if A == 1.0 or A == 0.0:
        return 0.0
    Q1 = A / (2.0 - A)
    Q2 = (2.0 * A**2) / (1.0 + A)
    variance = (
        A * (1.0 - A)
        + (n1 - 1) * (Q1 - A**2)
        + (n2 - 1) * (Q2 - A**2)
    ) / (n1 * n2)
    return math.sqrt(max(0.0, variance))


def _evaluate_signal(
    engine: Engine,
    eligible_fixtures: list[dict[str, Any]],
    signal_name: str,
) -> dict[str, Any]:
    stats_by_scenario: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "n_computed": 0, "n_unknown": 0, "values": []}
    )
    unknown_reasons: dict[str, int] = defaultdict(int)

    results_by_split: dict[str, dict[str, list[Decimal]]] = {
        "train": {"pos": [], "neg": []},
        "eval": {"pos": [], "neg": []},
        "pooled": {"pos": [], "neg": []},
    }

    direction = {
        "amount_deviation": AMOUNT_DEVIATION_DIRECTION,
        "transaction_velocity": TRANSACTION_VELOCITY_DIRECTION,
        "beneficiary_age": BENEFICIARY_AGE_DIRECTION,
    }[signal_name]

    for fx in eligible_fixtures:
        tx_id_str = fx["alert_spec"]["transaction_id"]
        tx_id = uuid.UUID(tx_id_str)
        gt = fx["ground_truth"]
        is_pos = gt != "CLEAN"
        split = fx["split"]
        sc = fx["scenario_class"]
        st = fx.get("scenario_subtype")

        # Ensure deterministic group ordering by creating a composite key,
        # we'll format it back later if needed,
        # but the prompt asks for statistics "Per scenario class/subtype".
        # Let's use a tuple for the group key.
        group_key = f"{sc}/{st}" if st else sc

        stats_by_scenario[group_key]["n"] += 1

        computed_val = None

        if signal_name == "amount_deviation":
            result_amt = compute_amount_deviation(engine, tx_id)
            if isinstance(result_amt, AmountDeviationComputed):
                computed_val = compute_risk_score(result_amt).value
            elif isinstance(result_amt, AmountDeviationUnknown):
                stats_by_scenario[group_key]["n_unknown"] += 1
                unknown_reasons[result_amt.reason] += 1
            else:
                stats_by_scenario[group_key]["n_unknown"] += 1
                unknown_reasons["unknown"] += 1

        elif signal_name == "transaction_velocity":
            result_vel = compute_transaction_velocity(engine, tx_id)
            computed_val = Decimal(result_vel.transaction_count)

        elif signal_name == "beneficiary_age":
            result_age = compute_beneficiary_age(engine, tx_id)
            if isinstance(result_age, BeneficiaryAgeComputed):
                computed_val = Decimal(result_age.beneficiary_age.total_seconds())
            elif isinstance(result_age, BeneficiaryAgeUnknown):
                stats_by_scenario[group_key]["n_unknown"] += 1
                unknown_reasons[result_age.reason] += 1
            else:
                stats_by_scenario[group_key]["n_unknown"] += 1
                unknown_reasons["unknown"] += 1

        if computed_val is not None:
            stats_by_scenario[group_key]["n_computed"] += 1
            stats_by_scenario[group_key]["values"].append(computed_val)

            # Apply fixed signal direction before AUC
            # If HIGHER is more suspicious, leave as is.
            # If LOWER is more suspicious, negate it.
            auc_val = computed_val if direction == "HIGHER" else -computed_val

            cls_key = "pos" if is_pos else "neg"
            results_by_split[split][cls_key].append(auc_val)
            results_by_split["pooled"][cls_key].append(auc_val)

    # Format scenario stats
    scenario_reports = {}
    for group_key in sorted(stats_by_scenario.keys()):
        stats = stats_by_scenario[group_key]
        vals = stats["values"]
        min_val = str(min(vals)) if vals else None
        max_val = str(max(vals)) if vals else None
        median_val = _compute_median(vals)
        median_str = str(median_val) if median_val is not None else None

        rep: dict[str, Any] = {
            "n": stats["n"],
            "n_computed": stats["n_computed"],
            "n_unknown": stats["n_unknown"],
            "min": min_val,
            "median": median_str,
            "max": max_val,
        }
        if signal_name == "beneficiary_age":
            # Just put the aggregate unknown reasons per group? No, prompt says:
            # "For beneficiary age also report: unknown count by reason" globally
            # per signal or per group?
            # It just says "For beneficiary age also report: unknown count by reason".
            # Let's put it at the signal level.
            pass
        scenario_reports[group_key] = rep

    # Format AUCs
    aucs: dict[str, dict[str, Any]] = {}
    for split_name in ["train", "eval", "pooled"]:
        data = results_by_split[split_name]
        pos = data["pos"]
        neg = data["neg"]
        if not pos or not neg:
            aucs[split_name] = {
                "auc": None,
                "n_positive": len(pos),
                "n_negative": len(neg),
                "unknown_excluded": True,
                "auc_se_hanley_mcneil": None,
                "reason": "missing positive or negative class observations",
            }
        else:
            auc_res = compute_roc_auc(pos, neg)
            auc_val = auc_res["auc"]
            se = compute_hanley_mcneil_se(auc_val, len(pos), len(neg))
            aucs[split_name] = {
                "auc": round(auc_val, 6),
                "n_positive": len(pos),
                "n_negative": len(neg),
                "unknown_excluded": True,
                "auc_se_hanley_mcneil": round(se, 6),
            }

    signal_report: dict[str, Any] = {
        "per_scenario_statistics": scenario_reports,
        "auc_results": aucs,
    }
    if signal_name == "beneficiary_age":
        signal_report["unknown_reasons"] = dict(sorted(unknown_reasons.items()))

    return signal_report


def measure_signal_baselines(
    engine: Engine,
    fixtures_manifest: dict[str, Any],
) -> dict[str, Any]:
    fixtures = fixtures_manifest["fixtures"]

    excluded_counts: dict[str, int] = defaultdict(int)
    eligible_fixtures = []

    for fx in fixtures:
        sc = fx.get("scenario_class")
        if sc == "worked_example":
            excluded_counts["worked_example"] += 1
            continue
        if sc == "insufficient_history":
            excluded_counts["insufficient_history"] += 1
            continue

        split = fx.get("split")
        if not split:
            raise ValueError("Missing split in fixture")
        if split not in ("train", "eval"):
            raise ValueError(f"Unexpected split: {split}")

        eligible_fixtures.append(fx)

    report = {
        "metadata": {
            "fixture_version": fixtures_manifest.get("fixture_version", "unknown"),
            "generator_version": fixtures_manifest.get("generator_version", "unknown"),
            "seed": fixtures_manifest.get("seed", "unknown"),
            "split_methodology": fixtures_manifest["split_methodology"],
            "methodology_tier": "PROTOTYPE",
            "signal_directions": {
                "amount_deviation": AMOUNT_DEVIATION_DIRECTION,
                "transaction_velocity": TRANSACTION_VELOCITY_DIRECTION,
                "beneficiary_age": BENEFICIARY_AGE_DIRECTION,
            },
            "explicit_disclaimer": (
                "No threshold was derived. No calibration was derived. "
                "No risk level was derived. No signal combination was derived. "
                "Signals were not modified. Data is synthetic. "
                "Sample size is small. Results reflect fixture design parameters. "
                "Results are not evidence of real-world AML detection performance."
            ),
        },
        "exclusions": dict(sorted(excluded_counts.items())),
        "signals": {
            "amount_deviation": _evaluate_signal(
                engine, eligible_fixtures, "amount_deviation"
            ),
            "transaction_velocity": _evaluate_signal(
                engine, eligible_fixtures, "transaction_velocity"
            ),
            "beneficiary_age": _evaluate_signal(
                engine, eligible_fixtures, "beneficiary_age"
            ),
        }
    }
    return report


if __name__ == "__main__":
    import os
    import sys

    from sqlalchemy import create_engine

    # Import generator only inside __main__
    from meridian.fixtures.generator_v03 import generate_fixtures_v03

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(db_url)
    res = generate_fixtures_v03("baseline_seed")

    report = measure_signal_baselines(engine, res["manifest"])
    print(canonical_json(report), end="")
