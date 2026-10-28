"""Deterministic account-unit DEV features; no runtime dispatch or AML decisions."""

from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import groupby
from typing import Any

from meridian.evaluation.external.financial import Account, account_features
from meridian.evaluation.external.ibm import Transaction

FEATURES = (
    "amount",
    "velocity",
    "median_ratio",
    "p95_ratio",
    "relative_velocity",
    "counterparty_novelty",
    "incoming_recency",
    "inflow_amount_match",
    "reciprocal_24h",
    "fan_in_24h",
)


def sender(tx: Transaction) -> Account:
    return tx.sender_bank, tx.sender_account


def receiver(tx: Transaction) -> Account:
    return tx.receiver_bank, tx.receiver_account


def features(
    account: Account,
    events: list[Transaction],
    lower: datetime,
    upper: datetime,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (t for t in events if t.timestamp < upper),
        key=lambda t: (t.timestamp, t.row_number),
    )
    outgoing = [t for t in ordered if sender(t) == account]
    baseline = {f["tx"].row_number: f for f in account_features(outgoing)}
    history: deque[Transaction] = deque()
    incoming: deque[Transaction] = deque()
    result = []
    for timestamp, group in groupby(ordered, key=lambda t: t.timestamp):
        batch = list(group)
        out = [t for t in batch if sender(t) == account]
        while history and history[0].timestamp < timestamp - timedelta(days=90):
            history.popleft()
        while incoming and incoming[0].timestamp < timestamp - timedelta(hours=24):
            incoming.popleft()
        if lower <= timestamp < upper and out:
            day = [
                t for t in history if t.timestamp >= timestamp - timedelta(hours=24)
            ] + out
            prior_week = [
                t
                for t in history
                if timestamp - timedelta(days=8)
                <= t.timestamp
                < timestamp - timedelta(days=1)
            ]
            invalid_history = any(t.paid is None or t.paid < 0 for t in history)
            invalid_incoming = any(
                t.received is None or t.received < 0 or t.paid is None or t.paid < 0
                for t in incoming
            )
            amounts = sorted(t.paid for t in history if t.paid is not None)
            for tx in out:
                b = baseline[tx.row_number]
                values: dict[str, float | None] = {k: None for k in FEATURES}
                reasons: dict[str, str | None] = {k: None for k in FEATURES}
                values.update(amount=b["amount"], velocity=b["velocity"])
                reasons.update(
                    amount=b["amount_reason"],
                    velocity=(
                        "UNSUPPORTED_OR_MISSING_AMOUNT_IN_24H"
                        if b["velocity"] is None
                        else None
                    ),
                )
                facts: dict[str, Any] = dict(
                    prior_outgoing_count=len(history),
                    prior_24h_incoming_count=len(incoming),
                    preceding_week_count=len(prior_week),
                )
                for name in ("median_ratio", "p95_ratio"):
                    reason = b["amount_reason"]
                    if reason is None and len(amounts) < 5:
                        reason = "INSUFFICIENT_HISTORY_LT_5"
                    if reason is None:
                        n = len(amounts)
                        denominator = (
                            (amounts[(n - 1) // 2] + amounts[n // 2]) / 2
                            if name == "median_ratio"
                            else amounts[(95 * n + 99) // 100 - 1]
                        )
                        facts[name + "_denominator"] = str(denominator)
                        if denominator == 0:
                            reason = "ZERO_DENOMINATOR"
                        elif tx.paid is not None:
                            values[name] = float(tx.paid / denominator)
                    reasons[name] = reason
                if timestamp < datetime(2019, 1, 1) + timedelta(days=8):
                    reasons["relative_velocity"] = "LEFT_CENSORED_8D"
                elif b["velocity"] is None or any(
                    t.paid is None or t.paid < 0 for t in prior_week
                ):
                    reasons["relative_velocity"] = "UNSUPPORTED_OR_MISSING_DIRECTION"
                elif not prior_week:
                    reasons["relative_velocity"] = "ZERO_PRIOR_WEEK_COUNT"
                else:
                    values["relative_velocity"] = float(
                        Decimal(len(day)) * 7 / len(prior_week)
                    )
                target_bad = tx.paid is None or tx.paid < 0
                if target_bad or invalid_history:
                    reasons["counterparty_novelty"] = "UNSUPPORTED_OR_MISSING_DIRECTION"
                elif not history:
                    reasons["counterparty_novelty"] = "NO_HISTORY"
                else:
                    values["counterparty_novelty"] = float(
                        receiver(tx) not in {receiver(t) for t in history}
                    )
                for name in (
                    "incoming_recency",
                    "inflow_amount_match",
                    "reciprocal_24h",
                    "fan_in_24h",
                ):
                    if receiver(tx) == account:
                        reasons[name] = "TARGET_SELF_TRANSFER"
                    elif target_bad or invalid_incoming:
                        reasons[name] = "UNSUPPORTED_OR_MISSING_DIRECTION"
                if not target_bad and not invalid_incoming and receiver(tx) != account:
                    values["reciprocal_24h"] = float(
                        any(sender(t) == receiver(tx) for t in incoming)
                    )
                    values["fan_in_24h"] = float(len({sender(t) for t in incoming}))
                    if incoming:
                        lag = (timestamp - incoming[-1].timestamp).total_seconds() / 60
                        facts["latest_incoming_lag_minutes"] = lag
                        values["incoming_recency"] = 1 / (1 + lag)
                    else:
                        reasons["incoming_recency"] = "NO_PRIOR_24H_INCOMING"
                    if tx.payment_currency == "Unknown" or any(
                        t.receiving_currency == "Unknown" for t in incoming
                    ):
                        reasons["inflow_amount_match"] = "MISSING_CURRENCY"
                    else:
                        matched = [
                            t
                            for t in incoming
                            if t.receiving_currency == tx.payment_currency
                        ]
                        total = sum(
                            (t.received for t in matched if t.received is not None),
                            Decimal(0),
                        )
                        facts["same_currency_inflow_sum"] = str(total)
                        if not matched or total == 0:
                            reasons["inflow_amount_match"] = (
                                "NO_POSITIVE_SAME_CURRENCY_INFLOW"
                            )
                        elif tx.paid is not None:
                            values["inflow_amount_match"] = float(
                                min(tx.paid, total) / max(tx.paid, total)
                            )
                result.append(
                    dict(
                        tx=tx,
                        values=values,
                        reasons=reasons,
                        facts=facts,
                        evidence=dict(
                            prior_outgoing_rows=[t.row_number for t in history],
                            current_24h_outgoing_rows=[t.row_number for t in day],
                            prior_24h_incoming_rows=[t.row_number for t in incoming],
                        ),
                    )
                )
        history.extend(out)
        incoming.extend(
            t for t in batch if receiver(t) == account and sender(t) != account
        )
    return result
