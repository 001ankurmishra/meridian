"""Tests for policy agent."""
# ruff: noqa: E501

import uuid
from typing import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from meridian.agents.policy.policy_agent import (
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
    retrieve_policy_evidence,
)
from meridian.agents.policy.retrieval import embed_document_chunk


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

            for idx, text in enumerate(chunks):
                chunk_id = uuid.uuid4()
                emb = embed_document_chunk(text)
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks "
                        "(chunk_id, document_id, chunk_text, chunk_index, embedding) "
                        "VALUES (:cid, :did, :ctext, :cindex, cast(:emb as vector(384)))"
                    ),
                    {
                        "cid": str(chunk_id),
                        "did": str(doc_id),
                        "ctext": text,
                        "cindex": idx,
                        "emb": str(emb),
                    },
                )
    yield


def test_all_above_threshold(
    app_role_engine: Engine, agent_synthetic_corpus: None
) -> None:
    with Session(app_role_engine) as session:
        res = retrieve_policy_evidence(
            session, "flibbertigibbet", top_k=2, confidence_threshold=0.0
        )
        assert isinstance(res, PolicyEvidenceFound)
        assert len(res.citations) > 0
        assert "flibbertigibbet" in res.citations[0].chunk_text
        assert res.citations[0].version == "v1"
        assert res.citations[0].is_synthetic is True


def test_mixed_threshold(app_role_engine: Engine, agent_synthetic_corpus: None) -> None:
    with Session(app_role_engine) as session:
        base_res = retrieve_policy_evidence(
            session, "flibbertigibbet", top_k=5, confidence_threshold=0.0
        )
        assert isinstance(base_res, PolicyEvidenceFound)
        assert len(base_res.citations) > 1

        highest_score = base_res.citations[0].rrf_score
        second_score = base_res.citations[1].rrf_score

        assert highest_score > second_score

        threshold = (highest_score + second_score) / 2.0

        filtered_res = retrieve_policy_evidence(
            session, "flibbertigibbet", top_k=5, confidence_threshold=threshold
        )
        assert isinstance(filtered_res, PolicyEvidenceFound)
        assert len(filtered_res.citations) == 1
        assert filtered_res.citations[0].rrf_score == highest_score


def test_all_below_threshold(
    app_role_engine: Engine, agent_synthetic_corpus: None
) -> None:
    with Session(app_role_engine) as session:
        # threshold=1.0 is impossible for RRF (max is ~0.033)
        res = retrieve_policy_evidence(
            session, "flibbertigibbet", top_k=5, confidence_threshold=1.0
        )
        assert isinstance(res, PolicyEvidenceInsufficient)


def test_zero_candidates(app_role_engine: Engine, superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    with Session(app_role_engine) as session:
        res = retrieve_policy_evidence(
            session, "test query", confidence_threshold=0.0
        )
        assert isinstance(res, PolicyEvidenceInsufficient)
