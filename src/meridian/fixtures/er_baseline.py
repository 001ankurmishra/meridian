import json
import os
import sys
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Engine, create_engine

from meridian.entity_resolution import compute_er_candidates, MATCHED_FIELDS, NORMALIZATION_VERSION, RULE_ID
from meridian.fixtures.generator_v05 import generate_fixtures_v05


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def measure_er_baseline(engine: Engine, manifest: dict[str, Any]) -> dict[str, Any]:
    er_gt = manifest.get("manifest", {}).get("er_ground_truth")
    if not er_gt:
        raise ValueError("Missing er_ground_truth in manifest")

    manifest_customer_ids = {str(c["customer_id"]) for c in manifest["customers"]}

    true_match_pairs = er_gt["true_match_pairs"]
    designed_negative_pairs = er_gt["designed_negative_pairs"]

    positive_gt = set()
    for pair in true_match_pairs:
        c1, c2 = pair["customer_ids"]
        c1, c2 = str(uuid.UUID(c1)), str(uuid.UUID(c2))
        if c1 > c2:
            c1, c2 = c2, c1
        positive_gt.add((c1, c2))

    with engine.connect() as conn:
        from sqlalchemy import text
        c_ids = [
            str(row[0]) for row in conn.execute(
                text("SELECT customer_id FROM customers")
            ).fetchall()
        ]

    db_customer_ids = set(c_ids)
    if db_customer_ids != manifest_customer_ids:
        raise RuntimeError("Database customers do not match manifest customers")

    N = len(c_ids)
    total_pairs = (N * (N - 1)) // 2

    all_unordered_pairs = set()
    for i in range(N):
        for j in range(i + 1, N):
            c1, c2 = c_ids[i], c_ids[j]
            if c1 > c2:
                c1, c2 = c2, c1
            all_unordered_pairs.add((c1, c2))

    negative_gt = all_unordered_pairs - positive_gt

    res = compute_er_candidates(engine)

    predicted_pairs = set()
    for cand in res.candidates:
        c1, c2 = str(cand.customer_id_a), str(cand.customer_id_b)
        if c1 > c2:
            c1, c2 = c2, c1
        predicted_pairs.add((c1, c2))

    tp_pairs = predicted_pairs & positive_gt
    fp_pairs = predicted_pairs & negative_gt
    unplanned_fp_pairs = set()

    # We map predicted false positives to designed negative categories
    designed_negative_set = set()
    for pair in designed_negative_pairs:
        c1, c2 = pair["customer_ids"]
        c1, c2 = str(uuid.UUID(c1)), str(uuid.UUID(c2))
        if c1 > c2:
            c1, c2 = c2, c1
        designed_negative_set.add((c1, c2))

    for p in fp_pairs:
        if p not in designed_negative_set:
            unplanned_fp_pairs.add(p)

    fn_pairs = positive_gt - predicted_pairs
    tn_pairs = negative_gt - predicted_pairs

    tp = len(tp_pairs)
    fp = len(fp_pairs)
    fn = len(fn_pairs)
    tn = len(tn_pairs)

    if tp + fp + fn + tn != total_pairs:
        raise RuntimeError(f"Pairs do not sum to total: {tp} + {fp} + {fn} + {tn} != {total_pairs}")

    abstentions: dict[str, int] = defaultdict(int)
    for inel in res.ineligible:
        reasons = list(inel.reasons)
        reasons.sort()
        key = "|".join(reasons)
        abstentions[key] += 1

    precision = (tp / (tp + fp)) if (tp + fp) > 0 else None
    recall = (tp / (tp + fn)) if (tp + fn) > 0 else None

    gt_pair_info = {}
    for pair in true_match_pairs:
        c1, c2 = pair["customer_ids"]
        c1, c2 = str(uuid.UUID(c1)), str(uuid.UUID(c2))
        if c1 > c2:
            c1, c2 = c2, c1
        gt_pair_info[(c1, c2)] = {
            "variant_transforms": pair["variant_transforms"],
            "within_v1_scope": pair["within_adr_v1_scope"],
        }

    stratified_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"n_pairs": 0, "n_found": 0})
    
    for p, info in gt_pair_info.items():
        vscope = str(info["within_v1_scope"])
        vt = str(info["variant_transforms"])
        key = f"scope={vscope}, transforms={vt}"
        
        stratified_counts[key]["n_pairs"] += 1
        if p in tp_pairs:
            stratified_counts[key]["n_found"] += 1

    stratified = {}
    for key, counts in stratified_counts.items():
        n_pairs = counts["n_pairs"]
        n_found = counts["n_found"]
        stratified[key] = {
            "n_pairs": n_pairs,
            "n_found": n_found,
            "recall": (n_found / n_pairs) if n_pairs > 0 else None,
            "numerator": n_found,
            "denominator": n_pairs
        }

    planted_consistency: list[dict[str, Any]] = []
    for p in tp_pairs:
        p_info = gt_pair_info.get(p)
        if p_info and not p_info["within_v1_scope"]:
            planted_consistency.append(
                {"pair": list(p), "status": "TP_BUT_OUT_OF_SCOPE", "info": p_info}
            )

    for p in fn_pairs:
        p_info = gt_pair_info.get(p)
        if p_info and p_info["within_v1_scope"]:
            planted_consistency.append(
                {"pair": list(p), "status": "FN_BUT_IN_SCOPE", "info": p_info}
            )

    fp_list: list[dict[str, Any]] = []
    for p in fp_pairs:
        cat = "UNPLANNED"
        for dnp in designed_negative_pairs:
            c1, c2 = dnp["customer_ids"]
            c1, c2 = str(uuid.UUID(c1)), str(uuid.UUID(c2))
            if c1 > c2:
                c1, c2 = c2, c1
            if (c1, c2) == p:
                cat = dnp["category"]
                break
        fp_list.append({"pair": list(p), "category": cat})

    fn_list: list[dict[str, Any]] = []
    for p in fn_pairs:
        p_info = gt_pair_info.get(p)
        fn_list.append({"pair": list(p), "info": p_info})

    fp_list.sort(key=lambda x: str(x["pair"]))
    fn_list.sort(key=lambda x: str(x["pair"]))
    planted_consistency.sort(key=lambda x: str(x["pair"]))

    result = {
        "metadata": {
            "tier": "PROTOTYPE",
            "evaluation_set_version": "0.5",
            "rule_id": RULE_ID,
            "normalization_version": NORMALIZATION_VERSION,
            "matched_fields": list(MATCHED_FIELDS),
            "explicit_disclaimer": (
                "This is generator-defined structural fidelity, "
                "not real-world ER performance. "
                "A candidate link is for human review "
                "and never an identity determination."
            ),
        },
        "metrics": {
            "customers": N,
            "total_unordered_pairs": total_pairs,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
        },
        "stratified_recall": dict(stratified),
        "abstention_reasons": dict(abstentions),
        "fp_list": fp_list,
        "fn_list": fn_list,
        "investigation_triggers": {
            "unplanned_fps": [list(p) for p in unplanned_fp_pairs],
            "planted_consistency_mismatches": planted_consistency,
        }
    }
    return result


if __name__ == "__main__":
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    engine = create_engine(db_url)
    manifest = generate_fixtures_v05(seed="er_corpus_v0.5_freeze")
    result = measure_er_baseline(engine, manifest)
    print(canonical_json(result))
