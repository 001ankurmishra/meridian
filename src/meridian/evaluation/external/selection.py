"""DEV-only validation and graded metrics for isolated RAG experiments.

No runtime model import, database access, label approval or final-set execution.
"""

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_dev_protocol(path: Path, corpus: Path) -> dict[str, Any]:
    protocol: dict[str, Any] = json.loads(path.read_text())
    if protocol.get("measurement_scope") != "DEV_ONLY":
        raise ValueError("This experimental runner accepts DEV only")
    if (
        protocol.get("label_status")
        != "PROPOSED_AI_AUTHORED_NOT_INDEPENDENTLY_VALIDATED"
    ):
        raise ValueError("Unexpected label provenance; explicit protocol review needed")
    if hashlib.sha256(corpus.read_bytes()).hexdigest() != protocol["corpus_sha256"]:
        raise ValueError("Corpus digest mismatch")
    rows = [json.loads(line) for line in corpus.read_text().splitlines()]
    known = {r["chunk_id"] for r in rows}
    if len(known) != len(rows):
        raise ValueError("Duplicate corpus IDs")
    seen_ids: set[str] = set()
    seen_text: set[str] = set()
    if not protocol["queries"]:
        raise ValueError("Empty protocol")
    for q in protocol["queries"]:
        normalized = " ".join(re.findall(r"\w+", q["query"].casefold()))
        if q["id"] in seen_ids or normalized in seen_text or not normalized:
            raise ValueError("Duplicate or empty query")
        seen_ids.add(q["id"])
        seen_text.add(normalized)
        if q["split"] != "DEV":
            raise ValueError("Final/HELDOUT queries are forbidden")
        grades = q["relevance_grades"]
        if not set(grades) <= known or any(
            type(g) is not int or g not in (1, 2, 3) for g in grades.values()
        ):
            raise ValueError("Unknown passage or invalid grade")
        relevant = any(g >= 2 for g in grades.values())
        if q["expectation"] not in ("RETRIEVE", "ABSTAIN") or (
            (q["expectation"] == "RETRIEVE") != relevant
        ):
            raise ValueError("Expectation contradicts relevance labels")
        if not q.get("family") or not q.get("rationale") or not q.get("applicability"):
            raise ValueError("Missing review metadata")
    return protocol


def ranked_metrics(
    returned: list[str], grades: dict[str, int], candidates: list[str]
) -> dict[str, float | bool | int | None]:
    """Treat >=2 as relevant; graded nDCG uses exponential gains incl. context.

    P@5 always has denominator five. Missing judgments are zero, which makes
    these provisional metrics pessimistic for unlabeled supporting passages.
    Candidate recall is measured before gating/reranking at the supplied depth.
    """
    if len(set(returned)) != len(returned) or len(set(candidates)) != len(candidates):
        raise ValueError("Duplicate rankings would inflate metrics")
    if not set(returned) <= set(candidates):
        raise ValueError("Returned passage absent from candidates")
    relevant = {cid for cid, grade in grades.items() if grade >= 2}
    top = returned[:5]
    hits = [cid in relevant for cid in top]
    dcg = sum(
        (2 ** grades.get(cid, 0) - 1) / math.log2(i + 2) for i, cid in enumerate(top)
    )
    ideal = sum(
        (2**grade - 1) / math.log2(i + 2)
        for i, grade in enumerate(sorted(grades.values(), reverse=True)[:5])
    )
    return {
        "relevant_passages": len(relevant),
        "hit_at_1": bool(hits and hits[0]),
        "precision_at_5": sum(hits) / 5,
        "recall_at_5": sum(hits) / len(relevant) if relevant else None,
        "mrr_at_5": next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0.0),
        "ndcg_at_5": dcg / ideal if ideal else None,
        "candidate_depth": len(candidates),
        "candidate_recall": len(relevant & set(candidates)) / len(relevant)
        if relevant
        else None,
        "abstained": not returned,
    }


def select_dev_threshold(
    positives: list[float], negatives: list[float]
) -> dict[str, float | int | str]:
    """Maximize balanced query acceptance/abstention on DEV, ties conservative.

    Return an exploratory fit, never a calibrated probability or final result.
    Values equal to the threshold pass. Include the all-abstain boundary.
    """
    if (
        not positives
        or not negatives
        or not all(math.isfinite(s) for s in positives + negatives)
    ):
        raise ValueError("Finite positive and negative DEV scores required")
    values = sorted(set(positives + negatives))
    thresholds = values + [math.nextafter(values[-1], math.inf)]
    threshold = max(
        thresholds,
        key=lambda t: (
            (
                sum(s >= t for s in positives) / len(positives)
                + sum(s < t for s in negatives) / len(negatives)
            )
            / 2,
            t,
        ),
    )
    return {
        "threshold": threshold,
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "objective": "DEV balanced query acceptance/abstention; conservative ties",
        "status": "EXPLORATORY_NOT_CALIBRATED",
    }
