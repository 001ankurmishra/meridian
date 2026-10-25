"""Pure ranking metrics and exact random-order expectations for the frozen protocol."""

import math
from fractions import Fraction
from typing import Any


def score_ranking(grades: list[int], ranking: list[int]) -> dict[str, Any]:
    n = len(grades)
    if n < 5 or sorted(ranking) != list(range(n)):
        raise ValueError("Expected a complete, unique ranking of at least five chunks.")
    if any(g not in (0, 1, 2) for g in grades):
        raise ValueError("Invalid relevance grade.")
    result: dict[str, Any] = {}
    for label, minimum in (("strict", 2), ("lenient", 1)):
        relevant = {i for i, grade in enumerate(grades) if grade >= minimum}
        r = len(relevant)
        if not r:
            result[label] = {"excluded": True}
            continue
        observed: dict[str, float] = {}
        random: dict[str, float] = {}
        observed["RR"] = 1 / next(
            i for i, index in enumerate(ranking, 1) if index in relevant
        )
        random["RR"] = float(
            sum(
                (
                    Fraction(math.comb(n - j, r - 1), j * math.comb(n, r))
                    for j in range(1, n - r + 2)
                ),
                Fraction(0),
            )
        )
        for k in (1, 3, 5):
            count = len(set(ranking[:k]) & relevant)
            observed[f"P@{k}"] = count / k
            observed[f"Recall@{k}"] = count / r
            observed[f"Hit@{k}"] = float(count > 0)
            random[f"P@{k}"] = float(Fraction(r, n))
            random[f"Recall@{k}"] = float(Fraction(k, n))
            random[f"Hit@{k}"] = float(
                1 - Fraction(math.comb(n - r, k) if n - r >= k else 0, math.comb(n, k))
            )
        result[label] = {"excluded": False, "observed": observed, "random": random}
    ndcg: dict[str, Any] = {"excluded": sum(grades) == 0}
    if sum(grades):
        observed = {}
        random = {}
        for k in (1, 3, 5):
            ideal = sum(
                g / math.log2(i + 2)
                for i, g in enumerate(sorted(grades, reverse=True)[:k])
            )
            observed[f"nDCG@{k}"] = (
                sum(
                    grades[index] / math.log2(i + 2)
                    for i, index in enumerate(ranking[:k])
                )
                / ideal
            )
            random[f"nDCG@{k}"] = (
                sum(grades) / n * sum(1 / math.log2(i + 2) for i in range(k)) / ideal
            )
        ndcg.update(observed=observed, random=random)
    result["graded"] = ndcg
    return result


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for cohort in sorted({row["cohort"] for row in rows}):
        cohort_rows = [row for row in rows if row["cohort"] == cohort]
        metrics: dict[str, Any] = {}
        for definition in ("strict", "lenient", "graded"):
            included = [
                row["metrics"][definition]
                for row in cohort_rows
                if not row["metrics"][definition]["excluded"]
            ]
            summary: dict[str, Any] = {
                "included": len(included),
                "excluded": len(cohort_rows) - len(included),
            }
            if included:
                for key in included[0]["observed"]:
                    observed = sum(item["observed"][key] for item in included) / len(
                        included
                    )
                    baseline = sum(item["random"][key] for item in included) / len(
                        included
                    )
                    summary[key] = {
                        "observed": observed,
                        "random": baseline,
                        "lift": observed - baseline,
                    }
            metrics[definition] = summary
        decisions: dict[str, int] = {}
        for row in cohort_rows:
            expected = row["expected_abstention"]
            outcome = (
                "NOT_ASSESSED"
                if expected == "NOT_ASSESSED"
                else (expected + "/" + row["system_decision"])
            )
            decisions[outcome] = decisions.get(outcome, 0) + 1
        result[cohort] = {
            "queries": len(cohort_rows),
            "metrics": metrics,
            "abstention_counts": decisions,
        }
    return result
