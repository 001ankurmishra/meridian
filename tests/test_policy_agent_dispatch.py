"""Tests for PolicyAgent dispatch."""
# ruff: noqa: E501
import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, text

from meridian.agents.policy.policy_agent import (
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
)
from meridian.agents.policy.retrieval import embed_document_chunk
from meridian.orchestration.investigation_run import create_investigation_run
from meridian.orchestration.policy_agent_dispatch import run_policy_agent


@pytest.fixture
def seeded_case_id(superuser_engine: Engine) -> Generator[uuid.UUID, None, None]:
    cid = uuid.uuid4()
    aid = uuid.uuid4()
    tid = uuid.uuid4()
    alert_id = uuid.uuid4()
    case_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with superuser_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO customers (customer_id, full_name, is_synthetic, created_at) VALUES (:cid, 'Test', true, :now)"),
            {"cid": cid, "now": now}
        )
        conn.execute(
            text("INSERT INTO accounts (account_id, customer_id, status, created_at) VALUES (:aid, :cid, 'active', :now)"),
            {"aid": aid, "cid": cid, "now": now}
        )
        conn.execute(
            text("INSERT INTO transactions (transaction_id, source_account_id, amount, currency, occurred_at, created_at) VALUES (:tid, :aid, 100, 'INR', :now, :now)"),
            {"tid": tid, "aid": aid, "now": now}
        )
        conn.execute(
            text("INSERT INTO alerts (alert_id, customer_id, transaction_id, created_at) VALUES (:alert_id, :cid, :tid, :now)"),
            {"alert_id": alert_id, "cid": cid, "tid": tid, "now": now}
        )
        conn.execute(
            text("INSERT INTO cases (case_id, alert_id, status, opened_at, created_at) VALUES (:case_id, :alert_id, 'OPEN', :now, :now)"),
            {"case_id": case_id, "alert_id": alert_id, "now": now}
        )

    yield case_id

    with superuser_engine.begin() as conn:
        conn.execute(text("DELETE FROM agent_runs"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases WHERE case_id = :case_id"), {"case_id": case_id})
        conn.execute(text("DELETE FROM alerts WHERE alert_id = :alert_id"), {"alert_id": alert_id})
        conn.execute(text("DELETE FROM transactions WHERE transaction_id = :tid"), {"tid": tid})
        conn.execute(text("DELETE FROM accounts WHERE account_id = :aid"), {"aid": aid})
        conn.execute(text("DELETE FROM customers WHERE customer_id = :cid"), {"cid": cid})


@pytest.fixture
def agent_synthetic_corpus(
    loader_role_engine: Engine, superuser_engine: Engine
) -> Generator[None, None, None]:
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    with loader_role_engine.begin() as conn:
        docs = [
            (
                "Doc1",
                "internal_policy",
                "v1",
                [
                    "This is a chunk about money laundering regulations.",
                    "Another chunk containing unrelated financial advice.",
                    "Peculiar wording to test lexical search specifically: flibbertigibbet.",
                ],
            ),
            (
                "Doc2",
                "internal_policy",
                "v1",
                [
                    "Semantic similarity target: The sky is blue and the sun is shining.",
                    "A completely random chunk.",
                ],
            ),
        ]

        for title, dtype, version, chunks in docs:
            doc_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    "INSERT INTO documents "
                    "(document_id, title, document_type, version, is_synthetic) "
                    "VALUES (:id, :t, :dt, :v, true)"
                ),
                {"id": str(doc_id), "t": title, "dt": dtype, "v": version},
            )

            for idx, text_chunk in enumerate(chunks):
                chunk_id = uuid.uuid4()
                emb = embed_document_chunk(text_chunk)
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks "
                        "(chunk_id, document_id, chunk_text, chunk_index, embedding) "
                        "VALUES (:cid, :did, :ctext, :cindex, cast(:emb as vector(384)))"
                    ),
                    {
                        "cid": str(chunk_id),
                        "did": str(doc_id),
                        "ctext": text_chunk,
                        "cindex": idx,
                        "emb": str(emb),
                    },
                )
    yield


def test_happy_path_evidence_found(
    app_role_engine: Engine, seeded_case_id: uuid.UUID, agent_synthetic_corpus: None
) -> None:
    # 1. Create InvestigationRun
    inv_run = create_investigation_run(app_role_engine, seeded_case_id)

    # 2. Run PolicyAgent dispatch
    res = run_policy_agent(app_role_engine, inv_run.investigation_run_id, "flibbertigibbet")

    # Assert result is what we expect
    assert isinstance(res, PolicyEvidenceFound)
    assert len(res.citations) > 0
    assert "flibbertigibbet" in res.citations[0].chunk_text

    # 3. Assert exact database state for agent_runs
    with app_role_engine.begin() as conn:
        ar_rows = conn.execute(
            text("SELECT agent_name, status, error FROM agent_runs WHERE investigation_run_id = :inv_id"),
            {"inv_id": inv_run.investigation_run_id},
        ).fetchall()
        assert len(ar_rows) == 1
        assert ar_rows[0][0] == "PolicyAgent"
        assert ar_rows[0][1] == "SUCCESS"
        assert ar_rows[0][2] is None


def test_domain_insufficient_evidence(
    app_role_engine: Engine, superuser_engine: Engine, seeded_case_id: uuid.UUID
) -> None:
    # Explicitly truncate so no candidates exist
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    inv_run = create_investigation_run(app_role_engine, seeded_case_id)

    # Dispatch agent
    res = run_policy_agent(app_role_engine, inv_run.investigation_run_id, "test query")

    # Assert correct domain return type
    assert isinstance(res, PolicyEvidenceInsufficient)

    # Assert exactly one agent_runs row, still status='SUCCESS'
    with app_role_engine.begin() as conn:
        ar_rows = conn.execute(
            text("SELECT agent_name, status, error FROM agent_runs WHERE investigation_run_id = :inv_id"),
            {"inv_id": inv_run.investigation_run_id},
        ).fetchall()
        assert len(ar_rows) == 1
        assert ar_rows[0][0] == "PolicyAgent"
        assert ar_rows[0][1] == "SUCCESS"
        assert ar_rows[0][2] is None


def test_execution_failure(app_role_engine: Engine, monkeypatch: pytest.MonkeyPatch, seeded_case_id: uuid.UUID) -> None:
    # Patch the domain function to raise an exception
    def mock_retrieve_policy_evidence(*args, **kwargs):
        raise ValueError("Simulated retrieval failure")

    import meridian.orchestration.policy_agent_dispatch
    monkeypatch.setattr(
        meridian.orchestration.policy_agent_dispatch,
        "retrieve_policy_evidence",
        mock_retrieve_policy_evidence,
    )

    inv_run = create_investigation_run(app_role_engine, seeded_case_id)

    with pytest.raises(ValueError, match="Simulated retrieval failure"):
        run_policy_agent(app_role_engine, inv_run.investigation_run_id, "query")

    with app_role_engine.begin() as conn:
        ar_rows = conn.execute(
            text("SELECT agent_name, status, error FROM agent_runs WHERE investigation_run_id = :inv_id"),
            {"inv_id": inv_run.investigation_run_id},
        ).fetchall()
        assert len(ar_rows) == 1
        assert ar_rows[0][0] == "PolicyAgent"
        assert ar_rows[0][1] == "FAILED"
        assert ar_rows[0][2] is not None
        assert "Simulated retrieval failure" in ar_rows[0][2]
