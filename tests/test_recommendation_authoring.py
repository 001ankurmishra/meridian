"""Tests for recommendation authoring layer."""

import uuid
from decimal import Decimal
from typing import Any, Generator, cast
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, text

from meridian.agents.policy.policy_agent import (
    PolicyCitation,
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
)
from meridian.agents.report.authoring import (
    INVESTIGATIVE_RECOMMENDATION_TEXT,
    AuthoringAlreadyPerformedError,
    AuthoringDrafts,
    AuthoringResult,
    FindingCategory,
    author_investigation_records,
    build_authoring_drafts,
)
from meridian.agents.report.outcome import (
    InvestigationOutcome,
    PolicyOutcome,
    TransactionOutcome,
)
from meridian.agents.report.report_assembly import assemble_report
from meridian.agents.transaction.amount_deviation import (
    AmountDeviationComputed,
    AmountDeviationUnknown,
)
from meridian.orchestration.investigation_orchestrator import orchestrate_investigation
from meridian.orchestration.transaction_agent_dispatch import (
    TransactionAgentDispatchResult,
)
from meridian.recommendations.recommendations import (
    record_recommendation,
    record_recommendation_with_connection,
)
from tests.db_cleanup import clean_investigation_run_dependencies


def test_u1_computed_tx_policy_found() -> None:
    tx_outcome = TransactionOutcome(
        result=AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=uuid.uuid4(),
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        agent_run_id=uuid.uuid4(),
    )
    policy_outcome = PolicyOutcome(
        result=PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=uuid.uuid4(),
                    document_id=uuid.uuid4(),
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                ),
            ]
        ),
        agent_run_id=uuid.uuid4(),
    )
    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=policy_outcome,
    )
    drafts = build_authoring_drafts(outcome)
    assert len(drafts.findings) == 2
    assert len(drafts.recommendations) == 1
    rec = drafts.recommendations[0]
    assert rec.text == INVESTIGATIVE_RECOMMENDATION_TEXT
    assert rec.finding_index == drafts.findings.index(
        next(f for f in drafts.findings if f.category == FindingCategory.INVESTIGATIVE)
    )


def test_u2_tx_unknown_policy_found() -> None:
    tx_outcome = TransactionOutcome(
        result=AmountDeviationUnknown(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=uuid.uuid4(),
            reason="insufficient history",
        ),
        agent_run_id=uuid.uuid4(),
    )
    policy_outcome = PolicyOutcome(
        result=PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=uuid.uuid4(),
                    document_id=uuid.uuid4(),
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                ),
            ]
        ),
        agent_run_id=uuid.uuid4(),
    )
    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=policy_outcome,
    )
    drafts = build_authoring_drafts(outcome)
    assert len(drafts.findings) == 1
    assert drafts.findings[0].category == FindingCategory.REFERENCE
    assert len(drafts.recommendations) == 0


def test_u3_no_transaction_policy_insufficient() -> None:
    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=None,
        graph=None,
        policy=PolicyOutcome(
            result=PolicyEvidenceInsufficient(),
            agent_run_id=uuid.uuid4(),
        ),
    )
    drafts = build_authoring_drafts(outcome)
    assert len(drafts.findings) == 0
    assert len(drafts.recommendations) == 0


def test_u4_no_transaction_policy_found() -> None:
    policy_outcome = PolicyOutcome(
        result=PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=uuid.uuid4(),
                    document_id=uuid.uuid4(),
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                ),
            ]
        ),
        agent_run_id=uuid.uuid4(),
    )
    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=None,
        graph=None,
        policy=policy_outcome,
    )
    drafts = build_authoring_drafts(outcome)
    assert len(drafts.findings) == 1
    assert len(drafts.recommendations) == 0


def test_u5_computed_tx_policy_insufficient() -> None:
    tx_outcome = TransactionOutcome(
        result=AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=uuid.uuid4(),
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        agent_run_id=uuid.uuid4(),
    )
    outcome = InvestigationOutcome(
        investigation_run_id=uuid.uuid4(),
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=PolicyOutcome(
            result=PolicyEvidenceInsufficient(), agent_run_id=uuid.uuid4()
        ),
    )
    drafts = build_authoring_drafts(outcome)
    assert len(drafts.findings) == 1
    assert drafts.findings[0].category == FindingCategory.INVESTIGATIVE
    assert len(drafts.recommendations) == 1


def test_u6_template_safety() -> None:
    text_val = INVESTIGATIVE_RECOMMENDATION_TEXT
    assert text_val == (
        "A human analyst should review this finding and its cited evidence, "
        "including the alerted transaction and the historical transactions "
        "used for comparison, before any determination is made."
    )
    assert text_val.strip()
    assert "human analyst" in text_val.lower()
    assert "review" in text_val.lower()
    assert not any(c.isdigit() for c in text_val)

    forbidden_phrases = [
        "the customer is laundering money",
        "this is confirmed fraud",
        "this account should be closed",
        "money laundering",
        "recommend escalation",
        "suspicious",
    ]
    for p in forbidden_phrases:
        assert p.lower() not in text_val.lower(), (
            f"Forbidden phrase '{p}' found in template"
        )  # noqa: E501

    forbidden_tokens = [
        "approve",
        "reject",
        "escalat",
        "freez",
        "frozen",
        "clos",
        "resolve",
        "file ",
        "sar",
    ]
    for t in forbidden_tokens:
        assert t.lower() not in text_val.lower(), (
            f"Forbidden token '{t}' found in template"
        )  # noqa: E501


def test_u7_determinism() -> None:
    outcome1 = InvestigationOutcome(
        investigation_run_id=uuid.UUID(int=1),
        alert_type="test",
        transaction=None,
        graph=None,
        policy=cast(PolicyOutcome, None),
    )
    outcome2 = InvestigationOutcome(
        investigation_run_id=uuid.UUID(int=1),
        alert_type="test",
        transaction=None,
        graph=None,
        policy=cast(PolicyOutcome, None),
    )
    d1 = build_authoring_drafts(outcome1)
    d2 = build_authoring_drafts(outcome2)
    assert d1 == d2


def test_u8_backward_compatibility() -> None:
    d = AuthoringDrafts(evidence=(), findings=(), recommendations=())
    assert d.recommendations == ()
    r = AuthoringResult(evidence_ids=(), finding_ids=(), recommendation_ids=())
    assert r.recommendation_ids == ()


# ---------------- DB TESTS ----------------


def _cleanup(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM document_chunks"))
        conn.execute(text("DELETE FROM documents"))
        clean_investigation_run_dependencies(conn)
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))
        conn.execute(text("DELETE FROM transactions"))
        conn.execute(text("DELETE FROM beneficiaries"))
        conn.execute(text("DELETE FROM accounts"))
        conn.execute(text("DELETE FROM customers"))


@pytest.fixture(autouse=True)
def clean_db(superuser_engine: Engine) -> Generator[None, None, None]:
    _cleanup(superuser_engine)
    yield
    _cleanup(superuser_engine)


def _seed_db(superuser_engine: Engine) -> uuid.UUID:
    case_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) "  # noqa: E501
                "VALUES (:cid, 'Test Customer', true, now())"
            ),
            {"cid": customer_id},
        )
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(transaction_id, amount, currency, occurred_at, created_at) "
                "VALUES (:tid, 100, 'INR', now(), now())"
            ),
            {"tid": tx_id},
        )
        conn.execute(
            text(
                "INSERT INTO alerts (alert_id, customer_id, transaction_id, alert_type, created_at) "  # noqa: E501
                "VALUES (:aid, :cid, :tid, 'TEST_ALERT', now())"
            ),
            {"aid": alert_id, "cid": customer_id, "tid": tx_id},
        )
        conn.execute(
            text(
                "INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) "
                "VALUES (:cid, :aid, 'OPEN', now(), now())"
            ),
            {"cid": case_id, "aid": alert_id},
        )
    return case_id


def _seed_investigation_run(app_role_engine: Engine, case_id: uuid.UUID) -> uuid.UUID:
    run_id = uuid.uuid4()
    with app_role_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO investigation_runs (investigation_run_id, case_id, status, created_at) "  # noqa: E501
                "VALUES (:rid, :cid, 'IN_PROGRESS', now())"
            ),
            {"rid": run_id, "cid": case_id},
        )
    return run_id


def _seed_agent_run(
    app_role_engine: Engine,
    investigation_run_id: uuid.UUID,
    module: str,
    agent_run_id: uuid.UUID | None = None,
) -> uuid.UUID:  # noqa: E501
    if agent_run_id is None:
        agent_run_id = uuid.uuid4()
    with app_role_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO agent_runs (agent_run_id, investigation_run_id, agent_name, tool_calls, status, started_at) "  # noqa: E501
                "VALUES (:aid, :irid, :module, '[]', 'SUCCESS', now())"
            ),
            {"aid": agent_run_id, "irid": investigation_run_id, "module": module},
        )
    return agent_run_id


def test_d1_record_recommendation_with_connection(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    run_id = _seed_investigation_run(app_role_engine, case_id)

    # 1. Rolls back when caller transaction rolls back
    try:
        with app_role_engine.begin() as conn:
            record_recommendation_with_connection(conn, run_id, "test 1", [])
            raise RuntimeError("abort")
    except RuntimeError:
        pass
    with app_role_engine.begin() as conn:
        c = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert c == 0

    # 2. Row persists visible inside caller's transaction
    with app_role_engine.begin() as conn:
        record_recommendation_with_connection(conn, run_id, "test 2", [])
        c = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert c == 1

    # 3. Unresolvable finding id raises ValueError
    with app_role_engine.begin() as conn:
        with pytest.raises(ValueError):
            record_recommendation_with_connection(
                conn, run_id, "test 3", [uuid.uuid4()]
            )  # noqa: E501

    # 4. record_recommendation still works
    record_recommendation(app_role_engine, run_id, "test 4", [])
    with app_role_engine.begin() as conn:
        c = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert c == 2


def test_d2_author_investigation_records(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    run_id = _seed_investigation_run(app_role_engine, case_id)
    tx_agent_id = _seed_agent_run(
        app_role_engine, run_id, "meridian.agents.transaction"
    )  # noqa: E501
    policy_agent_id = _seed_agent_run(app_role_engine, run_id, "meridian.agents.policy")

    with superuser_engine.begin() as conn:
        tx_id = conn.execute(
            text("SELECT transaction_id FROM transactions LIMIT 1")
        ).scalar()  # noqa: E501
        assert tx_id is not None
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic, created_at) VALUES (:did, 'T', 'internal_policy', '1', true, now())"
            ),  # noqa: E501
            {"did": doc_id},
        )
        conn.execute(
            text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_index, chunk_text, created_at) VALUES (:cid, :did, 0, 'T', now())"
            ),  # noqa: E501
            {"cid": chunk_id, "did": doc_id},
        )

    tx_outcome = TransactionOutcome(
        result=AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=tx_id,
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        agent_run_id=tx_agent_id,
    )
    policy_outcome = PolicyOutcome(
        result=PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                ),
            ]
        ),
        agent_run_id=policy_agent_id,
    )
    outcome = InvestigationOutcome(
        investigation_run_id=run_id,
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=policy_outcome,
    )

    with app_role_engine.begin() as conn:
        res = author_investigation_records(conn, outcome)

    assert len(res.recommendation_ids) == 1

    with app_role_engine.begin() as conn:
        f_count = conn.execute(text("SELECT count(*) FROM findings")).scalar()
        assert f_count == 2
        r_rows = conn.execute(
            text("SELECT text, based_on_finding_ids FROM recommendations")
        ).fetchall()  # noqa: E501
        assert len(r_rows) == 1
        assert r_rows[0][0] == INVESTIGATIVE_RECOMMENDATION_TEXT

        # Check based_on_finding_ids matches INVESTIGATIVE finding
        inv_f_id = conn.execute(
            text(
                "SELECT finding_id FROM findings WHERE observed_fact LIKE 'Transaction%' LIMIT 1"
            )  # noqa: E501
        ).scalar()
        assert r_rows[0][1] == [inv_f_id]


def test_d3_unknown_transaction(
    app_role_engine: Engine, superuser_engine: Engine
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    run_id = _seed_investigation_run(app_role_engine, case_id)
    tx_agent_id = _seed_agent_run(
        app_role_engine, run_id, "meridian.agents.transaction"
    )  # noqa: E501
    policy_agent_id = _seed_agent_run(app_role_engine, run_id, "meridian.agents.policy")

    with superuser_engine.begin() as conn:
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic, created_at) VALUES (:did, 'T', 'internal_policy', '1', true, now())"
            ),  # noqa: E501
            {"did": doc_id},
        )
        conn.execute(
            text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_index, chunk_text, created_at) VALUES (:cid, :did, 0, 'T', now())"
            ),  # noqa: E501
            {"cid": chunk_id, "did": doc_id},
        )

    tx_outcome = TransactionOutcome(
        result=AmountDeviationUnknown(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=uuid.uuid4(),
            reason="unknown",
        ),
        agent_run_id=tx_agent_id,
    )
    policy_outcome = PolicyOutcome(
        result=PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                ),
            ]
        ),
        agent_run_id=policy_agent_id,
    )
    outcome = InvestigationOutcome(
        investigation_run_id=run_id,
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=policy_outcome,
    )
    with app_role_engine.begin() as conn:
        res = author_investigation_records(conn, outcome)

    assert res.recommendation_ids == ()
    with app_role_engine.begin() as conn:
        c = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert c == 0


def test_d4_rollback(app_role_engine: Engine, superuser_engine: Engine) -> None:
    case_id = _seed_db(superuser_engine)
    run_id = _seed_investigation_run(app_role_engine, case_id)
    tx_agent_id = _seed_agent_run(
        app_role_engine, run_id, "meridian.agents.transaction"
    )  # noqa: E501

    with superuser_engine.begin() as conn:
        tx_id = conn.execute(
            text("SELECT transaction_id FROM transactions LIMIT 1")
        ).scalar()  # noqa: E501
        assert tx_id is not None

    tx_outcome = TransactionOutcome(
        result=AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=tx_id,
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        agent_run_id=tx_agent_id,
    )
    outcome = InvestigationOutcome(
        investigation_run_id=run_id,
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=cast(PolicyOutcome, None),
    )

    with patch(
        "meridian.agents.report.authoring.record_recommendation_with_connection",
        side_effect=RuntimeError,
    ):  # noqa: E501
        try:
            with app_role_engine.begin() as conn:
                author_investigation_records(conn, outcome)
        except RuntimeError:
            pass

    with app_role_engine.begin() as conn:
        e = conn.execute(text("SELECT count(*) FROM evidence")).scalar()
        f = conn.execute(text("SELECT count(*) FROM findings")).scalar()
        r = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert e == 0
        assert f == 0
        assert r == 0


def test_d5_guard(app_role_engine: Engine, superuser_engine: Engine) -> None:
    case_id = _seed_db(superuser_engine)
    run_id = _seed_investigation_run(app_role_engine, case_id)
    tx_agent_id = _seed_agent_run(
        app_role_engine, run_id, "meridian.agents.transaction"
    )  # noqa: E501

    with superuser_engine.begin() as conn:
        tx_id = conn.execute(
            text("SELECT transaction_id FROM transactions LIMIT 1")
        ).scalar()  # noqa: E501
        assert tx_id is not None

    tx_outcome = TransactionOutcome(
        result=AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=tx_id,
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        agent_run_id=tx_agent_id,
    )
    outcome = InvestigationOutcome(
        investigation_run_id=run_id,
        alert_type="test",
        transaction=tx_outcome,
        graph=None,
        policy=cast(PolicyOutcome, None),
    )
    with app_role_engine.begin() as conn:
        author_investigation_records(conn, outcome)

    with app_role_engine.begin() as conn:
        with pytest.raises(AuthoringAlreadyPerformedError):
            author_investigation_records(conn, outcome)

    with app_role_engine.begin() as conn:
        r = conn.execute(text("SELECT count(*) FROM recommendations")).scalar()
        assert r == 1


# ---------------- ORCHESTRATOR TESTS ----------------


def _patch_agents(
    m_tx: Any, m_graph: Any, m_policy: Any, tx_result: Any, policy_result: Any
) -> None:  # noqa: E501
    def tx_side_effect(
        engine: Engine,
        inv_id: uuid.UUID,
        tx_id: uuid.UUID,
        agent_run_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> TransactionAgentDispatchResult:  # noqa: E501
        if agent_run_id is None:
            agent_run_id = uuid.uuid4()
        _seed_agent_run(engine, inv_id, "meridian.agents.transaction", agent_run_id)
        return TransactionAgentDispatchResult(
            investigation_run_id=inv_id, result=tx_result
        )  # noqa: E501

    def policy_side_effect(
        engine: Engine,
        inv_id: uuid.UUID,
        query: str,
        agent_run_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> Any:  # noqa: E501
        if agent_run_id is None:
            agent_run_id = uuid.uuid4()
        _seed_agent_run(engine, inv_id, "meridian.agents.policy", agent_run_id)
        return policy_result

    m_tx.side_effect = tx_side_effect
    m_graph.return_value = None
    if policy_result is not None:
        m_policy.side_effect = policy_side_effect
    else:
        m_policy.return_value = None


@patch("meridian.orchestration.investigation_orchestrator.run_transaction_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_policy_agent")
def test_o1_and_c1(
    m_policy: Any,
    m_graph: Any,
    m_tx: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    with superuser_engine.begin() as conn:
        tx_id = conn.execute(
            text("SELECT transaction_id FROM transactions LIMIT 1")
        ).scalar()  # noqa: E501
        assert tx_id is not None
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic, created_at) VALUES (:did, 'T', 'internal_policy', '1', true, now())"
            ),  # noqa: E501
            {"did": doc_id},
        )
        conn.execute(
            text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_index, chunk_text, created_at) VALUES (:cid, :did, 0, 'T', now())"
            ),  # noqa: E501
            {"cid": chunk_id, "did": doc_id},
        )
        customer_id = conn.execute(
            text("SELECT customer_id FROM customers LIMIT 1")
        ).scalar()  # noqa: E501, F841

    _patch_agents(
        m_tx,
        m_graph,
        m_policy,
        AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=tx_id,
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                )
            ]
        ),
    )

    orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.begin() as conn:
        run = conn.execute(
            text(
                "SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).fetchone()  # noqa: E501
        assert run is not None
        assert run[1] == "COMPLETE"
        r = conn.execute(
            text(
                "SELECT count(*) FROM recommendations WHERE investigation_run_id = :rid"
            ),
            {"rid": run[0]},
        ).scalar()  # noqa: E501
        assert r == 1
        inv_f_id = conn.execute(
            text(
                "SELECT finding_id FROM findings WHERE observed_fact LIKE 'Transaction%' LIMIT 1"
            )  # noqa: E501
        ).scalar()

    # C1 test
    report = assemble_report(app_role_engine, run[0])
    assert len(report.recommendations) == 1
    assert report.recommendations[0].text == INVESTIGATIVE_RECOMMENDATION_TEXT
    assert report.recommendations[0].based_on_finding_ids == [inv_f_id]
    assert report.human_review_required is True


@patch("meridian.orchestration.investigation_orchestrator.run_transaction_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_policy_agent")
def test_o2(
    m_policy: Any,
    m_graph: Any,
    m_tx: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    with superuser_engine.begin() as conn:
        tx_id = conn.execute(
            text("SELECT transaction_id FROM transactions LIMIT 1")
        ).scalar()  # noqa: E501
        assert tx_id is not None

    _patch_agents(
        m_tx,
        m_graph,
        m_policy,
        AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=tx_id,
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        PolicyEvidenceInsufficient(),
    )

    orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.begin() as conn:
        run = conn.execute(
            text(
                "SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).fetchone()  # noqa: E501
        assert run is not None
        assert run[1] == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
        r = conn.execute(
            text(
                "SELECT count(*) FROM recommendations WHERE investigation_run_id = :rid"
            ),
            {"rid": run[0]},
        ).scalar()  # noqa: E501
        assert r == 1


@patch("meridian.orchestration.investigation_orchestrator.run_transaction_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_policy_agent")
def test_o3(
    m_policy: Any,
    m_graph: Any,
    m_tx: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    with superuser_engine.begin() as conn:
        doc_id = uuid.uuid4()
        chunk_id = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic, created_at) VALUES (:did, 'T', 'internal_policy', '1', true, now())"
            ),  # noqa: E501
            {"did": doc_id},
        )
        conn.execute(
            text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_index, chunk_text, created_at) VALUES (:cid, :did, 0, 'T', now())"
            ),  # noqa: E501
            {"cid": chunk_id, "did": doc_id},
        )

    _patch_agents(
        m_tx,
        m_graph,
        m_policy,
        AmountDeviationUnknown(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=uuid.uuid4(),
            reason="unknown",
        ),
        PolicyEvidenceFound(
            citations=[
                PolicyCitation(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    title="Doc",
                    version="1",
                    chunk_index=0,
                    chunk_text="text",
                    document_type="policy",
                    is_synthetic=False,
                    rrf_score=0.9,
                )
            ]
        ),
    )

    orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.begin() as conn:
        run = conn.execute(
            text(
                "SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).fetchone()  # noqa: E501
        assert run is not None
        assert run[1] == "INCOMPLETE_INSUFFICIENT_EVIDENCE"
        r = conn.execute(
            text(
                "SELECT count(*) FROM recommendations WHERE investigation_run_id = :rid"
            ),
            {"rid": run[0]},
        ).scalar()  # noqa: E501
        assert r == 0


@patch("meridian.agents.report.authoring.record_recommendation_with_connection")
@patch("meridian.orchestration.investigation_orchestrator.run_transaction_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_graph_agent")
@patch("meridian.orchestration.investigation_orchestrator.run_policy_agent")
def test_o4(
    m_policy: Any,
    m_graph: Any,
    m_tx: Any,
    m_rec: Any,
    app_role_engine: Engine,
    superuser_engine: Engine,
) -> None:  # noqa: E501
    case_id = _seed_db(superuser_engine)
    with superuser_engine.begin() as conn:
        tx_id = conn.execute(
            text("SELECT transaction_id FROM transactions LIMIT 1")
        ).scalar()  # noqa: E501
        assert tx_id is not None

    _patch_agents(
        m_tx,
        m_graph,
        m_policy,
        AmountDeviationComputed(
            source_account_id=uuid.uuid4(),
            alerted_transaction_id=tx_id,
            alerted_amount=Decimal("123.456"),
            historical_average=Decimal("100.0"),
            historical_transaction_count=2,
            deviation_multiple=Decimal("1.234"),
            source_transaction_ids=tuple(),
            currency="USD",
        ),
        PolicyEvidenceInsufficient(),
    )

    m_rec.side_effect = RuntimeError("authoring fail")

    with pytest.raises(RuntimeError):
        orchestrate_investigation(app_role_engine, case_id)

    with app_role_engine.begin() as conn:
        run = conn.execute(
            text(
                "SELECT investigation_run_id, status FROM investigation_runs WHERE case_id = :cid"
            ),
            {"cid": case_id},
        ).fetchone()  # noqa: E501
        assert run is not None
        assert run[1] == "FAILED"
        r = conn.execute(
            text(
                "SELECT count(*) FROM recommendations WHERE investigation_run_id = :rid"
            ),
            {"rid": run[0]},
        ).scalar()  # noqa: E501
        assert r == 0
        f = conn.execute(
            text("SELECT count(*) FROM findings WHERE investigation_run_id = :rid"),
            {"rid": run[0]},
        ).scalar()  # noqa: E501
        assert f == 0
        e = conn.execute(
            text("SELECT count(*) FROM evidence WHERE investigation_run_id = :rid"),
            {"rid": run[0]},
        ).scalar()  # noqa: E501
        assert e == 0
