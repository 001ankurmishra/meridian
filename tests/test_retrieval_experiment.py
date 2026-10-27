"""Guarded parity check for the isolated dimensional experiment adapter."""

import uuid

import pytest
from sqlalchemy import text

from meridian.evaluation.external.experiment import hybrid, setup_tables


def test_experimental_ranking_matches_native(app_role_engine, monkeypatch):
    from meridian.agents.policy import retrieval

    rows = [
        dict(chunk_id=f"test:{i}", title=title, version="2020", text=body)
        for i, (title, body) in enumerate(
            [
                ("Alpha", "customer identity verification"),
                ("Beta", "customer identity verification"),
                ("Gamma", "unrelated topic"),
            ]
        )
    ]
    vectors = [[1.0] + [0.0] * 383, [0.0, 1.0] + [0.0] * 382, [1.0] + [0.0] * 383]
    monkeypatch.setattr(retrieval, "embed_query", lambda _: vectors[0])
    with app_role_engine.begin() as conn:
        setup_tables(conn, rows, vectors, 384)
        conn.execute(
            text("""CREATE TEMP TABLE documents (
            document_id uuid, title text, document_type text,
            version text, is_synthetic boolean) ON COMMIT DROP""")
        )
        conn.execute(
            text("""CREATE TEMP TABLE document_chunks (
            chunk_id uuid, document_id uuid, chunk_index integer,
            chunk_text text, embedding vector(384)) ON COMMIT DROP""")
        )
        for i, row in enumerate(rows):
            cid = uuid.uuid5(uuid.NAMESPACE_URL, row["chunk_id"])
            conn.execute(
                text(
                    "INSERT INTO documents VALUES (:id,:title,'reference','2020',false)"
                ),
                {"id": cid, "title": row["title"]},
            )
            conn.execute(
                text("""INSERT INTO document_chunks
                VALUES (:id,:id,:idx,:body,cast(:v as vector(384)))"""),
                {"id": cid, "idx": i, "body": row["text"], "v": str(vectors[i])},
            )
        actual = hybrid(conn, "customer identity", vectors[0], 384)
        native = retrieval.retrieve_candidates(conn, "customer identity", top_k=50)
        assert [
            str(uuid.uuid5(uuid.NAMESPACE_URL, r["chunk_id"]))
            for r in actual["candidates"]
        ] == [str(r["chunk_id"]) for r in native]
        assert [r["rrf"] for r in actual["candidates"]] == pytest.approx(
            [r["rrf_score"] for r in native]
        )
        assert actual["max_cosine"] == native[0]["query_max_cosine_similarity"]


def test_different_dimension_stays_in_temporary_table(app_role_engine):
    with app_role_engine.begin() as conn:
        rows = [dict(chunk_id="base", title="base", version="1", text="identity")]
        vector = [1.0] + [0.0] * 767
        setup_tables(conn, rows, [vector], 768)
        assert hybrid(conn, "identity", vector, 768)["max_cosine"] == 1.0
        with pytest.raises(ValueError, match="shape"):
            hybrid(conn, "identity", vector, 384)
