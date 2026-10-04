import json
import os
import sys
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Engine, create_engine

from meridian.entity_resolution import compute_er_candidates
from meridian.fixtures.generator_v05 import generate_fixtures_v05


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def measure_er_baseline(engine: Engine, manifest: dict[str, Any]) -> dict[str, Any]:
    er_gt = manifest.get("manifest", {}).get("er_ground_truth")
    if not er_gt:
        raise ValueError("Missing er_ground_truth in manifest")

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

    all_unordered_pairs = set()
    for i in range(len(c_ids)):
        for j in range(i + 1, len(c_ids)):
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

    abstentions: dict[str, int] = defaultdict(int)
    for inel in res.ineligible:
        reasons = list(inel.reasons)
        reasons.sort()
        key = "|".join(reasons)
        abstentions[key] += 1

    tp = len(tp_pairs)
    fp = len(fp_pairs)
    fn = len(fn_pairs)
    tn = len(tn_pairs)

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

    stratified: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fn": 0})
    for p in tp_pairs:
        info = gt_pair_info.get(p)
        if info:
            vscope = str(info["within_v1_scope"])
            vt = str(info["variant_transforms"])
            key = f"scope={vscope}, transforms={vt}"
            stratified[key]["tp"] += 1

    for p in fn_pairs:
        info = gt_pair_info.get(p)
        if info:
            vscope = str(info["within_v1_scope"])
            vt = str(info["variant_transforms"])
            key = f"scope={vscope}, transforms={vt}"
            stratified[key]["fn"] += 1

    planted_consistency = []
    for p in tp_pairs:
        info = gt_pair_info.get(p)
        if info and not info["within_v1_scope"]:
            planted_consistency.append(
                {"pair": list(p), "status": "TP_BUT_OUT_OF_SCOPE", "info": info}
            )

    for p in fn_pairs:
        info = gt_pair_info.get(p)
        if info and info["within_v1_scope"]:
            planted_consistency.append(
                {"pair": list(p), "status": "FN_BUT_IN_SCOPE", "info": info}
            )

    fp_list = []
    for p in fp_pairs:
        cat = "UNKNOWN"
        for dnp in designed_negative_pairs:
            c1, c2 = dnp["customer_ids"]
            c1, c2 = str(uuid.UUID(c1)), str(uuid.UUID(c2))
            if c1 > c2:
                c1, c2 = c2, c1
            if (c1, c2) == p:
                cat = dnp["category"]
                break
        fp_list.append({"pair": list(p), "category": cat})

    for p in unplanned_fp_pairs:
        fp_list.append({"pair": list(p), "category": "UNPLANNED"})

    fn_list = []
    for p in fn_pairs:
        info = gt_pair_info.get(p)
        fn_list.append({"pair": list(p), "info": info})

    fp_list.sort(key=lambda x: str(x["pair"]))
    fn_list.sort(key=lambda x: str(x["pair"]))
    planted_consistency.sort(key=lambda x: str(x["pair"]))

    result = {
        "metadata": {
            "tier": "PROTOTYPE",
            "evaluation_set_version": "0.5",
            "explicit_disclaimer": (
                "This is generator-defined structural fidelity, "
                "not real-world ER performance. "
                "A candidate link is for human review "
                "and never an identity determination."
            ),
        },
        "metrics": {
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
