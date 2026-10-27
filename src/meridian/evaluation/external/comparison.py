"""Analyze cached DEV scores without additional inference or HELDOUT access."""

import argparse
import json
import random
import re
import statistics
from pathlib import Path
from typing import Any

from meridian.evaluation.external.ibm import sha256_file
from meridian.evaluation.external.selection import (
    canonical_hash,
    load_dev_protocol,
    ranked_metrics,
    select_dev_threshold,
)


def ineligible_request(query: str) -> str | None:
    """Experimental explicit-source eligibility, not a semantic safety guarantee.

    Only two international reference editions are present. Do not present them
    as a domestic statute, an absent edition or internal Meridian instructions.
    Rules inspect request text only, never relevance labels or query IDs.
    """
    q = query.casefold()
    if re.search(r"\bmeridian\b", q):
        return "No internal Meridian source in external reference corpus"
    if re.search(r"\b(indian|india|us federal|uk|singapore)\b", q) and re.search(
        r"\b(law|statutory|legally|mandatory|federal|penalty|binding)\b", q
    ):
        return "No verified domestic legal source"
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", q))
    if years - {"2020", "2024"}:
        return "Requested edition/date absent from corpus"
    return None


def fit(protocol: dict[str, Any], scores: dict[str, float]) -> dict[str, Any]:
    return select_dev_threshold(
        [
            scores[q["id"]]
            for q in protocol["queries"]
            if q["expectation"] == "RETRIEVE"
        ],
        [scores[q["id"]] for q in protocol["queries"] if q["expectation"] == "ABSTAIN"],
    )


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positives = [r for r in rows if r["expectation"] == "RETRIEVE"]
    negatives = [r for r in rows if r["expectation"] == "ABSTAIN"]
    metric_names = [
        "hit_at_1",
        "precision_at_5",
        "recall_at_5",
        "mrr_at_5",
        "ndcg_at_5",
        "candidate_recall",
    ]
    return dict(
        positive_queries=len(positives),
        negative_queries=len(negatives),
        labeled_relevant_passages=sum(r["relevant_passages"] for r in positives),
        positive_returned=sum(not r["abstained"] for r in positives),
        correct_negative_abstentions=sum(r["abstained"] for r in negatives),
        false_retrieval_rate=sum(not r["abstained"] for r in negatives)
        / len(negatives),
        **{name: statistics.mean(r[name] for r in positives) for name in metric_names},
        source_version_eligible_positive_citations=sum(
            r["eligible_citations"] for r in positives
        ),
        returned_positive_citations=sum(len(r["returned"]) for r in positives),
    )


def paired_intervals(
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    rng = random.Random(20261027)
    lookup = {r["id"]: r for r in baseline}
    result = {}
    for expectation, metric in [("RETRIEVE", "ndcg_at_5"), ("ABSTAIN", "abstained")]:
        families: dict[str, list[float]] = {}
        for r in candidate:
            if r["expectation"] == expectation:
                families.setdefault(r["family"], []).append(
                    float(r[metric]) - float(lookup[r["id"]][metric])
                )
        keys = sorted(families)
        samples = []
        for _ in range(1000):
            selected = [rng.choice(keys) for _ in keys]
            samples.append(statistics.mean(v for k in selected for v in families[k]))
        samples.sort()
        result[metric] = dict(
            families=len(keys),
            delta=statistics.mean(v for values in families.values() for v in values),
            percentile_95=[samples[24], samples[974]],
        )
    return result


def analyze(
    directory: Path, corpus: Path, inputs: list[Path], output: Path
) -> dict[str, Any]:
    protocol = load_dev_protocol(directory / "dev-proposals.json", corpus)
    if output.exists():
        raise FileExistsError("Analysis evidence already exists")
    docs = {r["chunk_id"]: r for r in map(json.loads, corpus.read_text().splitlines())}
    variants: dict[str, list[dict[str, Any]]] = {}
    fits = {}
    resources = {}
    for path in inputs:
        result = json.loads(path.read_text())
        if (
            result["protocol_sha256"] != canonical_hash(protocol)
            or result["corpus_sha256"] != sha256_file(corpus)
            or result["status"] != "MEASURED_DEV_ONLY"
            or [r["id"] for r in result["queries"]]
            != [q["id"] for q in protocol["queries"]]
        ):
            raise ValueError("Score provenance mismatch")
        name = result["model"]["model"].split("/")[-1]
        is_rerank = result["kind"] == "cross_encoder"
        scores = {
            r["id"]: max(r["reranker_scores"].values())
            if is_rerank
            else r["max_cosine"]
            for r in result["queries"]
        }
        fitted = fit(protocol, scores)
        fits[name] = fitted
        conditions = [
            "ungated",
            "dev_query_gate",
            "dev_passage_gate",
            "dev_passage_eligibility",
        ]
        if name == "bge-small-en-v1.5":
            conditions.insert(0, "original_gate")
        timings = [
            r.get(
                "rerank_seconds",
                r.get("query_encode_seconds", 0) + r.get("retrieval_seconds", 0),
            )
            for r in result["queries"]
        ]
        resources[name] = {
            k: result[k]
            for k in [
                "cold_model_load_seconds",
                "download_and_integrity_seconds",
                "document_encode_seconds",
                "peak_process_rss_bytes",
                "truncation_count",
                "platform",
                "machine",
                "libraries",
            ]
        }
        resources[name].update(
            warm_mean_seconds=statistics.mean(timings),
            warm_p95_seconds=sorted(timings)[int(0.95 * len(timings))],
            timing_scope="reranking only; add first stage"
            if is_rerank
            else "query embedding and SQL retrieval",
            evidence_sha256=sha256_file(path),
        )
        for condition in conditions:
            measured = []
            for q, r in zip(protocol["queries"], result["queries"], strict=True):
                candidates = r["candidates"]
                if is_rerank:
                    ranking = sorted(
                        candidates,
                        key=lambda c: (
                            -r["reranker_scores"][c["chunk_id"]],
                            candidates.index(c),
                        ),
                    )
                    passage_scores = r["reranker_scores"]
                else:
                    ranking = candidates
                    passage_scores = {c["chunk_id"]: c["cosine"] for c in candidates}
                threshold = (
                    0.620313 if condition == "original_gate" else fitted["threshold"]
                )
                rejected = condition != "ungated" and scores[q["id"]] < threshold
                reason = (
                    ineligible_request(q["query"])
                    if condition.endswith("eligibility")
                    else None
                )
                returned = (
                    []
                    if rejected or reason
                    else [
                        c["chunk_id"]
                        for c in ranking
                        if c["rrf"] >= 0.01
                        and (
                            not condition.startswith("dev_passage")
                            or passage_scores[c["chunk_id"]] >= threshold
                        )
                    ][:5]
                )
                eligible = sum(
                    docs[c]["source_id"] in q["applicability"]["source_ids"]
                    and docs[c]["version"] in q["applicability"]["versions"]
                    for c in returned
                )
                measured.append(
                    dict(
                        id=q["id"],
                        family=q["family"],
                        kind=q["kind"],
                        expectation=q["expectation"],
                        returned=returned,
                        eligibility_rejection=reason,
                        eligible_citations=eligible,
                        **ranked_metrics(
                            returned,
                            q["relevance_grades"],
                            [c["chunk_id"] for c in candidates],
                        ),
                    )
                )
            variants[name + "/" + condition] = measured
    baseline = variants["bge-small-en-v1.5/original_gate"]
    payload: dict[str, Any] = dict(
        status="EXPERIMENTAL_DEV_NOT_INDEPENDENT_VALIDATION",
        protocol_sha256=canonical_hash(protocol),
        fits=fits,
        resources=resources,
        comparison={
            name: dict(
                **summarize(rows),
                paired_delta_vs_original=paired_intervals(baseline, rows),
            )
            for name, rows in variants.items()
        },
        queries=variants,
        uncertainty=(
            "Paired proposed-family bootstrap; "
            "no label uncertainty or generalization guarantee."
        ),
        passage_gate_note=(
            "Query-optimal DEV threshold reused per passage as an "
            "ablation, not a separately optimized passage threshold."
        ),
    )
    output.write_text(json.dumps(payload, indent=2) + "\n")
    for name, metrics in payload["comparison"].items():
        print(
            name,
            "nDCG",
            round(metrics["ndcg_at_5"], 3),
            "negative abstentions",
            metrics["correct_negative_abstentions"],
            "/24",
        )
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args()
    analyze(args.directory, args.corpus, args.inputs, args.output)
