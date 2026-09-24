# ruff: noqa: E501
import os

import pytest
from sqlalchemy import Engine, create_engine, text

from meridian.agents.policy.chunking import chunk_document
from meridian.loader.policy_corpus import POLICY_CORPUS_V1
from meridian.loader.policy_ingest import ingest_policy_corpus


def test_corpus_contract() -> None:
    assert len(POLICY_CORPUS_V1) == 4

    titles = set()
    for doc in POLICY_CORPUS_V1:
        titles.add(doc.title)
        assert doc.is_synthetic is True
        assert doc.document_type == "internal_policy"
        assert doc.version
        assert doc.source_url_or_ref
        assert doc.title.startswith("Synthetic Internal Policy — ")
        assert doc.text

        text_lower = doc.text.lower()
        assert "money laundering" not in text_lower
        assert "recommend escalation" not in text_lower
        assert "suspicious" not in text_lower

        chunks = chunk_document(doc.text)
        assert len(chunks) > 0

    assert len(titles) == 4


@pytest.fixture
def engines() -> tuple[Engine, Engine]:
    loader_url = os.environ.get("LOADER_DATABASE_URL")
    migrator_url = os.environ.get("DATABASE_URL")
    if not loader_url or not migrator_url:
        pytest.skip("Required DB URLs not set")
    return create_engine(loader_url), create_engine(migrator_url)


def test_ingestion(engines: tuple[Engine, Engine]) -> None:
    loader_engine, migrator_engine = engines

    from meridian.loader.main import clear_data

    with migrator_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))

    clear_data(migrator_engine)
    docs_inserted, chunks_inserted = ingest_policy_corpus(loader_engine)

    assert docs_inserted == 4
    total_expected_chunks = sum(len(chunk_document(d.text)) for d in POLICY_CORPUS_V1)
    assert chunks_inserted == total_expected_chunks

    with loader_engine.connect() as conn:
        doc_count = conn.execute(text("SELECT count(*) FROM documents")).scalar()
        assert doc_count == 4

        chunk_count = conn.execute(
            text("SELECT count(*) FROM document_chunks")
        ).scalar()
        assert chunk_count == total_expected_chunks

        chunks = conn.execute(
            text(
                "SELECT document_id, chunk_index, embedding FROM document_chunks ORDER BY document_id, chunk_index"
            )
        ).fetchall()

        invalid_dims = conn.execute(
            text("SELECT count(*) FROM document_chunks WHERE vector_dims(embedding) != 384")
        ).scalar()
        assert invalid_dims == 0

        doc_indices: dict[str, list[int]] = {}
        for row in chunks:
            doc_id, idx, emb = row
            assert emb is not None

            if doc_id not in doc_indices:
                doc_indices[doc_id] = []
            doc_indices[doc_id].append(idx)

        for doc_id, indices in doc_indices.items():
            assert indices == list(range(len(indices)))

        is_synthetic_count = conn.execute(
            text("SELECT count(*) FROM documents WHERE is_synthetic = true")
        ).scalar()
        assert is_synthetic_count == 4


def test_reset_reload_repeatability(engines: tuple[Engine, Engine]) -> None:
    loader_engine, migrator_engine = engines
    from meridian.loader.main import clear_data

    with migrator_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))

    clear_data(migrator_engine)
    d1, c1 = ingest_policy_corpus(loader_engine)

    clear_data(migrator_engine)
    d2, c2 = ingest_policy_corpus(loader_engine)

    assert d1 == d2
    assert c1 == c2

    with loader_engine.connect() as conn:
        doc_count = conn.execute(text("SELECT count(*) FROM documents")).scalar()
        assert doc_count == 4


def test_real_retrieval_integration(engines: tuple[Engine, Engine]) -> None:
    loader_engine, migrator_engine = engines
    from sqlalchemy.orm import Session

    from meridian.agents.policy.policy_agent import (
        PolicyEvidenceFound,
        retrieve_policy_evidence,
    )
    from meridian.loader.main import clear_data

    with migrator_engine.begin() as conn:
        conn.execute(text("DELETE FROM audit_events"))
        conn.execute(text("DELETE FROM investigation_runs"))
        conn.execute(text("DELETE FROM cases"))
        conn.execute(text("DELETE FROM alerts"))

    clear_data(migrator_engine)
    ingest_policy_corpus(loader_engine)

    alert_mapping = {
        "large_transaction": "Synthetic Internal Policy — Large / unusual transaction review procedure",
        "new_beneficiary": "Synthetic Internal Policy — New beneficiary review procedure",
        "rapid_movement": "Synthetic Internal Policy — Rapid movement of funds review procedure",
    }

    with Session(migrator_engine) as session:
        for alert_type, expected_title in alert_mapping.items():
            res = retrieve_policy_evidence(session, alert_type)
            assert isinstance(res, PolicyEvidenceFound)

            assert res.citations[0].is_synthetic is True

            top_5_titles = [c.title for c in res.citations[:5]]
            assert expected_title in top_5_titles
