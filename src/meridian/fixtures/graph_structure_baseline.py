import os
import sys
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Engine, create_engine

from meridian.agents.graph.structure_signals import (
    ChainDepthComputed,
    ChainDepthIncompleteTruncated,
    CycleFound,
    CycleIncompleteTruncated,
    CycleNotFound,
    compute_cycle_through_account,
    compute_outbound_chain_depth,
)
from meridian.fixtures.amount_deviation_baseline import canonical_json


def measure_graph_baseline(
    engine: Engine, fixtures_manifest: dict[str, Any]
) -> dict[str, Any]:
    fixtures = fixtures_manifest["fixtures"]
    seed = fixtures_manifest.get("seed", "unknown")

    # Exclusions
    excluded_counts: dict[str, int] = defaultdict(int)
    eligible_fixtures = []

    for fx in fixtures:
        gt = fx.get("graph_ground_truth")
        if not gt:
            excluded_counts["missing_graph_ground_truth"] += 1
            continue
        if not gt.get("applicable", False):
            excluded_counts[gt.get("reason", "not_applicable")] += 1
            continue

        eligible_fixtures.append(fx)

    # Directed Cycle Stats
    cycle_stats_by_scenario: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "n": 0,
            "n_found": 0,
            "n_not_found": 0,
            "n_truncated": 0,
            "tp": 0,
            "fp": 0,
            "tn": 0,
            "fn": 0,
        }
    )
    cycle_totals = {
        "tp": 0,
        "fp": 0,
        "tn": 0,
        "fn": 0,
        "n": 0,
        "n_truncated": 0,
        "n_exact_match": 0,
    }

    # Outbound Chain Stats
    chain_stats_by_scenario: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "n": 0,
            "n_computed": 0,
            "n_truncated": 0,
            "exact_matches": 0,
            "sum_abs_error": 0,
        }
    )
    chain_totals = {"n": 0, "n_truncated": 0, "n_exact_match": 0, "sum_abs_error": 0}

    for fx in eligible_fixtures:
        gt = fx["graph_ground_truth"]
        acct_id_str = gt["start_account_id"]
        acct_id = uuid.UUID(acct_id_str)

        sc = fx["scenario_class"]
        st = fx.get("scenario_subtype")
        group_key = f"{sc}/{st}" if st else sc

        # Directed Cycle
        y_true_cycle = gt["has_directed_cycle"]
        cycle_res = compute_cycle_through_account(engine, acct_id)

        cycle_stats = cycle_stats_by_scenario[group_key]
        cycle_stats["n"] += 1
        cycle_totals["n"] += 1

        y_pred_cycle = False
        if isinstance(cycle_res, CycleFound):
            cycle_stats["n_found"] += 1
            y_pred_cycle = True
        elif isinstance(cycle_res, CycleNotFound):
            cycle_stats["n_not_found"] += 1
        elif isinstance(cycle_res, CycleIncompleteTruncated):
            cycle_stats["n_truncated"] += 1
            cycle_totals["n_truncated"] += 1
            # Treated as negative prediction for match purposes

        if y_pred_cycle == y_true_cycle:
            cycle_totals["n_exact_match"] += 1
            if y_true_cycle:
                cycle_stats["tp"] += 1
                cycle_totals["tp"] += 1
            else:
                cycle_stats["tn"] += 1
                cycle_totals["tn"] += 1
        else:
            if y_pred_cycle:
                cycle_stats["fp"] += 1
                cycle_totals["fp"] += 1
            else:
                cycle_stats["fn"] += 1
                cycle_totals["fn"] += 1

        # Outbound Chain
        y_true_chain = gt["max_outbound_chain_depth"]
        chain_res = compute_outbound_chain_depth(engine, acct_id)

        chain_stats = chain_stats_by_scenario[group_key]
        chain_stats["n"] += 1
        chain_totals["n"] += 1

        y_pred_chain = 0
        if isinstance(chain_res, ChainDepthComputed):
            y_pred_chain = chain_res.depth
            chain_stats["n_computed"] += 1
        elif isinstance(chain_res, ChainDepthIncompleteTruncated):
            y_pred_chain = chain_res.lower_bound_depth
            chain_stats["n_truncated"] += 1
            chain_totals["n_truncated"] += 1

        if y_pred_chain == y_true_chain:
            chain_stats["exact_matches"] += 1
            chain_totals["n_exact_match"] += 1

        abs_err = abs(y_true_chain - y_pred_chain)
        chain_stats["sum_abs_error"] += abs_err
        chain_totals["sum_abs_error"] += abs_err

    # Format cycle scenario stats
    formatted_cycle_scenario_stats = {}
    for group_key in sorted(cycle_stats_by_scenario.keys()):
        formatted_cycle_scenario_stats[group_key] = dict(
            cycle_stats_by_scenario[group_key]
        )

    formatted_chain_scenario_stats = {}
    for group_key in sorted(chain_stats_by_scenario.keys()):
        st = chain_stats_by_scenario[group_key]
        formatted_chain_scenario_stats[group_key] = {
            "n": st["n"],
            "n_computed": st["n_computed"],
            "n_truncated": st["n_truncated"],
            "exact_matches": st["exact_matches"],
            "mean_absolute_error": (
                round(st["sum_abs_error"] / st["n"], 6) if st["n"] > 0 else 0.0
            ),
        }

    report = {
        "metadata": {
            "fixture_version": fixtures_manifest.get("fixture_version", "unknown"),
            "generator_version": fixtures_manifest.get("generator_version", "unknown"),
            "seed": seed,
            "methodology_tier": "PROTOTYPE",
            "metric_interpretation_note": (
                "These signals measure deterministic structural fidelity against an oracle, "
                "not probabilistic predictive utility. Therefore ROC-AUC is mathematically "
                "inappropriate. Exact match rate and MAE are reported."
            ),
            "explicit_disclaimer": (
                "No threshold was selected. No calibration was performed. "
                "No risk-level mapping was derived. These primitives do not assign risk scores. "
                "Their predictive utility for AML behavior remains uncalibrated."
            ),
        },
        "exclusions": dict(sorted(excluded_counts.items())),
        "signals": {
            "directed_cycle": {
                "per_scenario_statistics": formatted_cycle_scenario_stats,
                "structural_fidelity": {
                    "n_applicable": cycle_totals["n"],
                    "n_exact_match": cycle_totals["n_exact_match"],
                    "exact_match_rate": (
                        round(cycle_totals["n_exact_match"] / cycle_totals["n"], 6)
                        if cycle_totals["n"] > 0
                        else 0.0
                    ),
                    "truncation_rate": (
                        round(cycle_totals["n_truncated"] / cycle_totals["n"], 6)
                        if cycle_totals["n"] > 0
                        else 0.0
                    ),
                    "confusion_matrix": {
                        "TP": cycle_totals["tp"],
                        "FP": cycle_totals["fp"],
                        "TN": cycle_totals["tn"],
                        "FN": cycle_totals["fn"],
                    },
                },
            },
            "outbound_chain_depth": {
                "per_scenario_statistics": formatted_chain_scenario_stats,
                "structural_fidelity": {
                    "n_applicable": chain_totals["n"],
                    "n_exact_match": chain_totals["n_exact_match"],
                    "exact_match_rate": (
                        round(chain_totals["n_exact_match"] / chain_totals["n"], 6)
                        if chain_totals["n"] > 0
                        else 0.0
                    ),
                    "truncation_rate": (
                        round(chain_totals["n_truncated"] / chain_totals["n"], 6)
                        if chain_totals["n"] > 0
                        else 0.0
                    ),
                    "mean_absolute_error": (
                        round(chain_totals["sum_abs_error"] / chain_totals["n"], 6)
                        if chain_totals["n"] > 0
                        else 0.0
                    ),
                },
            },
        },
    }

    return report


if __name__ == "__main__":
    from meridian.fixtures.generator_v04 import generate_fixtures_v04

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(db_url)
    res = generate_fixtures_v04("baseline_seed")

    report = measure_graph_baseline(engine, res["manifest"])
    print(canonical_json(report), end="")
