"""Diagnostic uncertainty from deterministic ties at a fixed review budget."""

from typing import Any


def tie_bounds(rows: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    if budget < 0:
        raise ValueError("Budget must be nonnegative")
    known = sorted(
        (r for r in rows if r["score"] is not None),
        key=lambda r: (-r["score"], r["source_row"]),
    )
    selected = known[:budget]
    if not selected:
        return dict(reviewed=0, tp_min=0, tp_max=0)
    cutoff = selected[-1]["score"]
    above = [r for r in known if r["score"] > cutoff]
    tied = [r for r in known if r["score"] == cutoff]
    slots = len(selected) - len(above)
    p = sum(r["label"] for r in tied)
    n = len(tied) - p
    fixed = sum(r["label"] for r in above)
    return dict(
        reviewed=len(selected),
        cutoff=cutoff,
        tied=len(tied),
        tied_positive=p,
        tied_slots=slots,
        tp_min=fixed + max(0, slots - n),
        tp_max=fixed + min(slots, p),
        interpretation="Bounds over possible tie orderings; not a confidence interval",
    )
