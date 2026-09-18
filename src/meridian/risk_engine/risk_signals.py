"""Risk Engine: Compute and persist single-signal risk evaluations.

EXECUTION BOUNDARY & PROVENANCE LIMITATION:
This module provides a PROTOTYPE, single-signal (`amount_deviation`) heuristic.
The formula is an unmodified pass-through: `value = deviation_multiple`, which
is equivalent to weight = 1.0 on the sole signal.
This is an explicit, arbitrary implementation choice, not derived from any
evaluation, sample, or tuning process. It operates identically to the precedent
for unspecified PROTOTYPE parameters (e.g., `confidence_threshold = 0.01` in
policy_agent).
This value does NOT represent an overall AML risk score, a customer risk level,
or a comprehensive risk assessment of any kind.

Furthermore, this module is NOT automatically invoked as part of any investigation
run, dispatch, or orchestration flow. F2/Orchestrator integration is unimplemented.
This module is called explicitly by whatever caller holds a valid
`investigation_run_id`.

Provenance is limited to `investigation_run_id` + `customer_id` + `transaction_id` +
`created_at`. There is no `agent_runs` linkage and no `created_by` column, which
is a known, accepted MVP limitation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Engine, text

from meridian.agents.transaction.amount_deviation import AmountDeviationComputed


@dataclass(frozen=True)
class RiskScoreResult:
    """The evaluated risk score result to persist."""

    signal_type: str
    value: Decimal
    methodology: str


def compute_risk_score(signal: AmountDeviationComputed) -> RiskScoreResult:
    """Compute the risk score for an amount deviation signal.

    Callers are responsible for branching on `AmountDeviationComputed` vs.
    `AmountDeviationUnknown` before invoking this function; this function does
    not perform runtime type validation and relies on its static type signature
    plus caller discipline to exclude `Unknown` inputs.

    Args:
        signal: The computed amount deviation from the TransactionAgent slice.

    Returns:
        RiskScoreResult: A frozen dataclass carrying the signal type, the raw
        computed value (which is a pass-through of the deviation multiple), and
        the methodology tag 'PROTOTYPE'.
    """
    return RiskScoreResult(
        signal_type="amount_deviation",
        value=signal.deviation_multiple,
        methodology="PROTOTYPE",
    )


def record_risk_signal(
    engine: Engine,
    investigation_run_id: uuid.UUID | None,
    customer_id: uuid.UUID,
    transaction_id: uuid.UUID | None,
    result: RiskScoreResult,
) -> RiskScoreResult:
    """Record a computed risk signal into the database.

    Args:
        engine: Application-role SQLAlchemy Engine.
        investigation_run_id: UUID of the investigation run.
        customer_id: UUID of the customer associated with the transaction.
        transaction_id: UUID of the transaction being scored.
        result: The computed risk score to persist.

    Returns:
        The same RiskScoreResult passed in, matching the project's convention.

    Side effects:
        Inserts exactly one row into `risk_signals`.
    """
    risk_signal_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO risk_signals (
                    risk_signal_id,
                    investigation_run_id,
                    customer_id,
                    transaction_id,
                    signal_type,
                    value,
                    model_version,
                    methodology,
                    created_at
                ) VALUES (
                    :risk_signal_id,
                    :investigation_run_id,
                    :customer_id,
                    :transaction_id,
                    :signal_type,
                    :value,
                    NULL,
                    :methodology,
                    :created_at
                )
                """
            ),
            {
                "risk_signal_id": risk_signal_id,
                "investigation_run_id": investigation_run_id,
                "customer_id": customer_id,
                "transaction_id": transaction_id,
                "signal_type": result.signal_type,
                "value": result.value,
                "methodology": result.methodology,
                "created_at": created_at,
            },
        )

    return result
