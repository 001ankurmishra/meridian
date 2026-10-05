import uuid
from decimal import Decimal

from meridian.agents.report.authoring import FindingCategory, build_authoring_drafts
from meridian.agents.report.outcome import InvestigationOutcome, TransactionOutcome
from meridian.agents.transaction.amount_deviation import AmountDeviationComputed


def test_characterization_amount_deviation() -> None:
    agent_run_id = uuid.uuid4()
    alerted_id = uuid.uuid4()
    source_acc = uuid.uuid4()
    src_id1 = uuid.uuid4()
    src_id2 = uuid.uuid4()

    result = AmountDeviationComputed(
        alerted_transaction_id=alerted_id,
        source_account_id=source_acc,
        historical_transaction_count=2,
        alerted_amount=Decimal("150.00"),
        historical_average=Decimal("50.00"),
        deviation_multiple=Decimal("3.00"),
        currency="USD",
        source_transaction_ids=(src_id1, src_id2),
    )

    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=TransactionOutcome(result=result, agent_run_id=agent_run_id),
        graph=None,
        policy=None,  # type: ignore
    )

    drafts = build_authoring_drafts(outcome)

    # Assert evidence
    assert len(drafts.evidence) == 3
    keys = {e.key: e for e in drafts.evidence}
    assert f"alerted_{alerted_id}" in keys
    assert f"input_{src_id1}" in keys
    assert f"input_{src_id2}" in keys

    # Assert findings
    assert len(drafts.findings) == 1
    finding = drafts.findings[0]
    assert finding.category == FindingCategory.INVESTIGATIVE
    assert (
        finding.observed_fact
        == f"Transaction {alerted_id} from source account {source_acc} has a recorded amount of 150.00 USD."  # noqa: E501
    )
    assert (
        finding.derived_signal
        == "The recorded amount is 3.00 times the mean amount (50.00 USD) of 2 outgoing transaction(s) from the customer's accounts in the 90 days before this transaction."  # noqa: E501
    )
    assert (
        finding.interpretation
        == "This describes relative size only. No validated threshold defines an unusual deviation (PROTOTYPE), so no conclusion about the activity is drawn."  # noqa: E501
    )
    assert finding.confidence == "LOW"

    # Assert recommendations
    assert len(drafts.recommendations) == 1
    rec = drafts.recommendations[0]
    assert rec.finding_index == 0
    assert (
        rec.text
        == "A human analyst should review this finding and its cited evidence, including the alerted transaction and the historical transactions used for comparison, before any determination is made."  # noqa: E501
    )
