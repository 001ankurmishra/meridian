import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from meridian.agents.report.authoring import FindingCategory, build_authoring_drafts
from meridian.agents.report.outcome import InvestigationOutcome, TransactionOutcome
from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
)
from meridian.agents.transaction.beneficiary_age import BeneficiaryAgeComputed
from meridian.agents.transaction.transaction_velocity import TransactionVelocityComputed
from meridian.risk_engine.risk_signals import (
    compute_beneficiary_age_risk_score,
    compute_velocity_risk_score,
)


def test_risk_signal_velocity() -> None:
    vel = TransactionVelocityComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        window_hours=24,
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        transaction_count=5,
        source_transaction_ids=(),
    )
    score = compute_velocity_risk_score(vel)
    assert score.signal_type == "transaction_velocity"
    assert score.value == Decimal("5")
    assert score.methodology == "PROTOTYPE"


def test_risk_signal_beneficiary_age() -> None:
    age = timedelta(days=2, hours=3, minutes=4, seconds=5, microseconds=123456)
    ben = BeneficiaryAgeComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        destination_account_id=uuid.uuid4(),
        alerted_occurred_at=datetime.now(timezone.utc),
        beneficiary_added_at=datetime.now(timezone.utc) - age,
        beneficiary_age=age,
        beneficiary_ids=(),
    )
    score = compute_beneficiary_age_risk_score(ben)
    assert score.signal_type == "beneficiary_age"
    expected_sec = Decimal(2 * 86400 + 3 * 3600 + 4 * 60 + 5) + Decimal("0.123456")
    assert score.value == expected_sec
    assert score.methodology == "PROTOTYPE"


def test_authoring_both_signals() -> None:
    vel = TransactionVelocityComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        window_hours=24,
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        transaction_count=5,
        source_transaction_ids=(uuid.uuid4(), uuid.uuid4()),
    )
    ben = BeneficiaryAgeComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        destination_account_id=uuid.uuid4(),
        alerted_occurred_at=datetime.now(timezone.utc),
        beneficiary_added_at=datetime.now(timezone.utc),
        beneficiary_age=timedelta(days=1),
        beneficiary_ids=(uuid.uuid4(),),
    )
    amt = AmountDeviationComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        historical_transaction_count=1,
        alerted_amount=Decimal("100"),
        historical_average=Decimal("50"),
        deviation_multiple=Decimal("2"),
        currency="USD",
        source_transaction_ids=(),
    )

    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=TransactionOutcome(
            result=amt,
            agent_run_id=uuid.uuid4(),
            velocity_result=vel,
            beneficiary_age_result=ben,
        ),
        graph=None,
        policy=None,  # type: ignore
    )
    drafts = build_authoring_drafts(outcome)

    # Amount + velocity (2 input) + ben (1 input) = 1 + 2 + 1 = 4 evidence?
    # amount creates 1 alerted. velocity creates 2. ben creates 1. -> 4.
    assert len(drafts.evidence) == 4

    # 3 findings
    assert len(drafts.findings) == 3
    assert len(drafts.recommendations) == 3

    vel_finding = next(
        f for f in drafts.findings if "Transaction velocity" in f.observed_fact
    )
    assert vel_finding.category == FindingCategory.INVESTIGATIVE
    assert vel_finding.interpretation is not None and "criminal activity" in vel_finding.interpretation  # noqa: E501

    ben_finding = next(
        f for f in drafts.findings if "Beneficiary age" in f.observed_fact
    )
    assert "1 day(s)" in ben_finding.observed_fact


def test_authoring_independence() -> None:
    vel = TransactionVelocityComputed(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        window_hours=24,
        window_start=datetime.now(timezone.utc),
        window_end=datetime.now(timezone.utc),
        transaction_count=5,
        source_transaction_ids=(uuid.uuid4(),),
    )
    amt = AmountDeviationUnknown(
        alerted_transaction_id=uuid.uuid4(),
        source_account_id=uuid.uuid4(),
        reason="foo",
    )

    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=TransactionOutcome(
            result=amt,
            agent_run_id=uuid.uuid4(),
            velocity_result=vel,
            beneficiary_age_result=None,
        ),
        graph=None,
        policy=None,  # type: ignore
    )
    drafts = build_authoring_drafts(outcome)

    assert len(drafts.findings) == 1
    assert "Transaction velocity" in drafts.findings[0].observed_fact
