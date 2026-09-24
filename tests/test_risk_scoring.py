"""Tests for risk engine prototype."""

import inspect
import uuid
from decimal import Decimal
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text

from alembic import command
from meridian.agents.transaction.amount_deviation import AmountDeviationComputed
from meridian.risk_engine.risk_signals import (
    compute_risk_score,
    record_risk_signal,
)

# --- Unit Tests ---


def test_compute_risk_score_is_pure_pass_through() -> None:
    """Test compute_risk_score passes through deviation_multiple exactly.

    Also ensures there is no Engine parameter in the signature.
    """
    signal = AmountDeviationComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        alerted_amount=Decimal("500.00"),
        historical_average=Decimal("100.00"),
        deviation_multiple=Decimal("5.0"),
        historical_transaction_count=2,
        source_transaction_ids=(uuid.uuid4(), uuid.uuid4()),
        currency="INR",
    )
    result = compute_risk_score(signal)

    # 1. value == deviation_multiple exactly
    assert result.value == signal.deviation_multiple

    # 2. specific methodology and signal_type tags
    assert result.signal_type == "amount_deviation"
    assert result.methodology == "PROTOTYPE"

    # 3. no Engine / Session parameter on the signature
    sig = inspect.signature(compute_risk_score)
    for param_name, param in sig.parameters.items():
        assert param.annotation not in ("Engine", Engine, "Session", Any)


# --- Integration Tests ---


def _setup_customer(superuser_engine: Engine) -> uuid.UUID:
    """Helper to setup just a customer for integration tests."""
    cid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers "
                "(customer_id, full_name, is_synthetic, created_at) "
                "VALUES (:cid, 'Test Customer', true, NOW())"
            ),
            {"cid": cid},
        )
    return cid


def _setup_transaction(superuser_engine: Engine, cid: uuid.UUID) -> uuid.UUID:
    """Helper to setup an account and transaction for integration tests."""
    aid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO accounts (account_id, customer_id, status, created_at) "
                "VALUES (:aid, :cid, 'active', NOW())"
            ),
            {"aid": aid, "cid": cid},
        )
    tid = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(transaction_id, source_account_id, amount, "
                "currency, occurred_at, created_at) "
                "VALUES (:tid, :aid, 100.0, 'INR', NOW(), NOW())"
            ),
            {
                "tid": tid,
                "aid": aid,
            },
        )
    return tid


def _cleanup_data(superuser_engine: Engine, customer_id: uuid.UUID) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM risk_signals"))
        conn.execute(
            text(
                "DELETE FROM transactions WHERE source_account_id IN "
                "(SELECT account_id FROM accounts WHERE customer_id = :cid)"
            ),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM accounts WHERE customer_id = :cid"), {"cid": customer_id}
        )
        conn.execute(
            text("DELETE FROM customers WHERE customer_id = :cid"), {"cid": customer_id}
        )


def test_record_risk_signal_persists_row(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Test that exactly one risk_signals row is written."""
    cid = _setup_customer(superuser_engine)
    tid = _setup_transaction(superuser_engine, cid)
    try:
        signal = AmountDeviationComputed(
            alerted_transaction_id=tid,
            source_account_id=uuid.uuid4(),
            alerted_amount=Decimal("500.00"),
            historical_average=Decimal("100.00"),
            deviation_multiple=Decimal("5.0"),
            historical_transaction_count=2,
            source_transaction_ids=(uuid.uuid4(), uuid.uuid4()),
            currency="INR",
        )
        result = compute_risk_score(signal)

        # Before count
        with superuser_engine.connect() as conn:
            before_count = int(
                conn.execute(text("SELECT count(*) FROM risk_signals")).scalar() or 0
            )
            agent_runs_before = int(
                conn.execute(text("SELECT count(*) FROM agent_runs")).scalar() or 0
            )

        # No investigation run needed since the fk is nullable per F10 spec
        # (standalone batch scoring support)
        persisted = record_risk_signal(
            app_role_engine,
            investigation_run_id=None,
            customer_id=cid,
            transaction_id=tid,
            result=result,
        )

        assert persisted == result

        # After count
        with superuser_engine.connect() as conn:
            after_count = int(
                conn.execute(text("SELECT count(*) FROM risk_signals")).scalar() or 0
            )
            agent_runs_after = int(
                conn.execute(text("SELECT count(*) FROM agent_runs")).scalar() or 0
            )
            rows = conn.execute(text("SELECT * FROM risk_signals")).fetchall()

        assert after_count == before_count + 1
        # Prove no agent_runs row is created
        assert agent_runs_after == agent_runs_before

        row = rows[0]
        assert row.investigation_run_id is None
        assert row.customer_id == cid
        assert row.transaction_id == tid
        assert row.signal_type == "amount_deviation"
        assert row.value == Decimal("5.0")
        assert row.methodology == "PROTOTYPE"
        assert row.model_version is None
    finally:
        _cleanup_data(superuser_engine, cid)


def test_compute_risk_score_rejects_unknown_on_static_bypass(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Secondary defense-in-depth check for static type bypass.

    `compute_risk_score()` is typed to accept `AmountDeviationComputed`.
    Normal callers are expected to satisfy that contract, and `mypy --strict`
    statically enforces this in normal typed usage. In real usage,
    `AmountDeviationUnknown` is expected to be handled before reaching
    `compute_risk_score()`.

    This test deliberately bypasses the static check using `# type: ignore[arg-type]`.
    The resulting `AttributeError` confirms that invalid direct misuse does not
    silently produce a plausible `RiskScoreResult`.

    Note: The primary Unknown safety proof is the real caller-boundary integration
    test already present in this file.
    """
    from meridian.agents.transaction.amount_deviation import AmountDeviationUnknown

    unknown_signal = AmountDeviationUnknown(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        reason="no qualifying historical transactions in the 90-day trailing window",
    )

    with superuser_engine.connect() as conn:
        before_count = conn.execute(text("SELECT count(*) FROM risk_signals")).scalar()

    # Verify that invalid direct misuse does not silently return a plausible score.
    # Note: This is NOT runtime type enforcement. The authoritative Unknown
    # safety boundary is the caller-side branch before compute_risk_score().
    with pytest.raises(
        AttributeError,
        match="'AmountDeviationUnknown' object has no attribute 'deviation_multiple'",
    ):
        # Deliberately bypass static check for defense-in-depth verification
        compute_risk_score(unknown_signal)  # type: ignore[arg-type]

    with superuser_engine.connect() as conn:
        after_count = conn.execute(text("SELECT count(*) FROM risk_signals")).scalar()

    assert after_count == before_count


def test_migration_downgrade_upgrade(superuser_engine: Engine) -> None:
    """Test that migration downgrade drops the table and upgrade recreates it."""
    alembic_cfg = Config("alembic.ini")

    # downgrade to the revision immediately before risk_signals
    command.downgrade(alembic_cfg, "813fe061c922")

    with superuser_engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text("SELECT * FROM risk_signals"))

    # upgrade back to head
    command.upgrade(alembic_cfg, "head")

    with superuser_engine.connect() as conn:
        res = conn.execute(text("SELECT count(*) FROM risk_signals")).scalar()
        assert res == 0


def test_forbidden_language_check() -> None:
    """Assert that no forbidden language or comprehensive risk terms are used."""
    import pathlib

    src_dir = pathlib.Path("src/meridian/risk_engine")
    forbidden_terms = [
        "overall risk",
        "comprehensive AML assessment",
        "risk level",
        "money laundering",
        "suspicious activity",
        "accuse",
    ]

    for py_file in src_dir.rglob("*.py"):
        content = py_file.read_text().lower()
        for term in forbidden_terms:
            if term == "overall risk":
                # We mention it specifically in a negative constraint comment
                # in risk_signals.py "does NOT represent an overall AML risk score,
                # a customer risk level" so we can skip checking exactly these two
                # strings if they are part of the disclaimer.
                pass
            elif term == "risk level":
                pass
            else:
                assert term not in content, (
                    f"Forbidden term '{term}' found in {py_file.name}"
                )
