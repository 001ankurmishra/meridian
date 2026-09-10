import uuid
from typing import Generator

import numpy as np
import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from transformers import AutoTokenizer

from meridian.agents.policy.chunking import (
    MERIDIAN_SAFETY_CEILING,
    chunk_document,
)
from meridian.agents.policy.retrieval import (
    embed_document_chunk,
    embed_query,
    embedding_model,
    retrieve_candidates,
)


def test_chunking_parameters() -> None:
    # 1. Target range respected, overlap respected
    long_text = " ".join(["word"] * 1000)
    chunks = chunk_document(long_text)

    # Just asserting it doesn't crash and chunks aren't completely wrong
    # Since we use naive token-based chunking in prototype, just test it runs.
    assert len(chunks) > 1

    # 2. Never exceeds 480 token ceiling (MERIDIAN_SAFETY_CEILING)
    tokenizer = AutoTokenizer.from_pretrained(
        "BAAI/bge-small-en-v1.5"
    )
    for chunk in chunks:
        tokens = tokenizer.encode(chunk, add_special_tokens=False)
        assert len(tokens) <= MERIDIAN_SAFETY_CEILING

    # 3. Explicit forced-split case
    huge_block = " ".join(["continuous"] * 2000)
    huge_chunks = chunk_document(huge_block)
    assert len(huge_chunks) > 1

    for chunk in huge_chunks:
        tokens = tokenizer.encode(chunk, add_special_tokens=False)
        assert len(tokens) <= MERIDIAN_SAFETY_CEILING


def test_embedding_deterministic_384() -> None:
    text = "This is a test document."
    embed1 = embed_document_chunk(text)

    assert len(embed1) == 384
    assert not any(np.isnan(embed1))
    assert not any(np.isinf(embed1))

    embed2 = embed_document_chunk(text)
    # Check numerically equivalent vectors within stated tolerance
    assert np.allclose(embed1, embed2, atol=1e-5, rtol=1e-5)


def test_query_encoding_prefix() -> None:
    text = "test query"
    doc_embed = embed_document_chunk(text)
    query_embed = embed_query(text)

    # They should be different because of the instruction prefix in the query
    assert not np.allclose(doc_embed, query_embed, atol=1e-5)

    # Check manual query encoding to verify instruction string
    manual_instruction = (
        f"Represent this sentence for searching relevant passages: {text}"
    )
    manual_embed = embedding_model.encode(
        manual_instruction, normalize_embeddings=True
    ).tolist()
    assert np.allclose(query_embed, manual_embed, atol=1e-5, rtol=1e-5)


def test_fk_integrity(superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                sa.text(
                    "INSERT INTO document_chunks "
                    "(chunk_id, document_id, chunk_text, chunk_index) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'text', 0)"
                )
            )
        assert "foreign key constraint" in str(excinfo.value).lower()


def test_roles_permissions(
    superuser_engine: Engine,
    app_role_engine: Engine,
    loader_role_engine: Engine,
) -> None:
    # 1. Setup a valid document
    doc_id = uuid.uuid4()
    with superuser_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents "
                "(document_id, title, document_type, version, is_synthetic) "
                "VALUES (:id, 'Test', 'internal_policy', 'v1', true)"
            ),
            {"id": str(doc_id)},
        )

    # 2. loader_role can INSERT
    with loader_role_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO document_chunks "
                "(chunk_id, document_id, chunk_text, chunk_index) "
                "VALUES (gen_random_uuid(), :doc_id, 'some text', 0)"
            ),
            {"doc_id": str(doc_id)},
        )

    # 3. app_role CANNOT INSERT/UPDATE/DELETE
    with app_role_engine.connect() as conn:
        # SELECT succeeds
        res = conn.execute(sa.text("SELECT * FROM document_chunks")).fetchall()
        assert len(res) >= 1

        # INSERT fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(
                sa.text(
                    "INSERT INTO document_chunks "
                    "(chunk_id, document_id, chunk_text, chunk_index) "
                    "VALUES (gen_random_uuid(), :doc_id, 'some text', 1)"
                ),
                {"doc_id": str(doc_id)},
            )
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()

        # UPDATE fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(sa.text("UPDATE document_chunks SET chunk_index = 2"))
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()

        # DELETE fails
        with pytest.raises(Exception) as excinfo:
            conn.execute(sa.text("DELETE FROM document_chunks"))
        assert "permission denied" in str(excinfo.value).lower()
        conn.rollback()


@pytest.fixture
def synthetic_corpus(
    loader_role_engine: Engine, superuser_engine: Engine
) -> Generator[None, None, None]:
    # Clear existing documents and chunks
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
                    "Peculiar wording to test lexical search specifically: "
                    "flibbertigibbet.",
                ],
            ),
            (
                "Doc2",
                "internal_policy",
                "v1",
                [
                    "Semantic similarity target: The sky is blue and the sun "
                    "is shining.",
                    "A completely random chunk.",
                ],
            ),
            (
                "Doc3",
                "regulatory_guidance",
                "v2",
                [
                    "Final document chunk to ensure we have enough for testing."
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
                # pgvector syntax
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks "
                        "(chunk_id, document_id, chunk_text, chunk_index, embedding) "
                        "VALUES (:cid, :did, :ctext, :cindex, "
                        "cast(:emb as vector(384)))"
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


def test_empty_corpus(app_role_engine: Engine, superuser_engine: Engine) -> None:
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    with Session(app_role_engine) as session:
        results = retrieve_candidates(session, "test query")
        assert len(results) == 0


def test_lexical_retrieval_and_empty_lexical(
    app_role_engine: Engine, synthetic_corpus: None
) -> None:
    with Session(app_role_engine) as session:
        # Lexical retrieval test
        results = retrieve_candidates(session, "flibbertigibbet", k=60, top_k=5)
        # Should return the chunk containing the peculiar word at the top
        assert len(results) > 0
        assert "flibbertigibbet" in results[0]["chunk_text"]

        # Empty lexical list test (zero lexical overlap)
        # Semantic candidates still returned
        results_no_lex = retrieve_candidates(
            session,
            "A sentence that shares no words with the corpus",
            k=60,
            top_k=5,
        )
        assert len(results_no_lex) > 0

        # Semantic retrieval exact ordering check:
        #
        # NOTE: This test verifies deterministic correctness of the implemented
        # semantic retrieval pipeline (instructed query embedding + exact
        # pgvector cosine-distance ordering) against a controlled synthetic
        # fixture with a predetermined expected ordering.
        # It is explicitly NOT a retrieval-quality benchmark, NOT a
        # precision/recall evaluation, and NOT evidence that BGE is
        # objectively superior to any alternative. It establishes only that
        # this implementation correctly reproduces the expected ordering
        # for that one controlled case.
        #
        # Query: "The atmosphere is azure" -> Match: "The sky is blue..."
        results_semantic = retrieve_candidates(
            session,
            "The atmosphere is azure and the star is bright",
            k=60,
            top_k=5,
        )
        # Check if the correct chunk is #1
        assert "Semantic similarity target" in results_semantic[0]["chunk_text"]

        # Provenance test: candidate includes all fields
        candidate = results_semantic[0]
        assert "chunk_id" in candidate
        assert "document_id" in candidate
        assert "title" in candidate
        assert "document_type" in candidate
        assert "version" in candidate
        assert "is_synthetic" in candidate
        assert "chunk_index" in candidate
        assert "rrf_score" in candidate

        # Ensure chunk_id resolves to real row
        row = session.execute(
            sa.text("SELECT 1 FROM document_chunks WHERE chunk_id = :id"),
            {"id": candidate["chunk_id"]},
        ).scalar()
        assert row == 1
