# ruff: noqa: E501
"""Tests for A0: Deterministic policy retrieval across lexical, vector, and RRF stages.

Covers:
- Pure Python total-ordering and tie-break tests for RRF
- Permutation invariance
- Python vs SQL COLLATE "C" comparator verification
- Built-in policy corpus (title, version, chunk_index) uniqueness
- Disposable database tests:
    - Lexical score ties
    - Vector distance ties
    - Insertion order independence
    - Fused top-k boundary ties
    - Logical corpus reload stability (G2)
    - Duplicate logical tuples fixed-DB determinism (G1)
    - Lexical document join row-set preservation
"""

import uuid
from typing import Any, Dict, List

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from meridian.agents.policy.chunking import chunk_document
from meridian.agents.policy.policy_agent import (
    PolicyEvidenceFound,
    PolicyEvidenceInsufficient,
    retrieve_policy_evidence,
)
from meridian.agents.policy.retrieval import (
    embed_document_chunk,
    retrieve_candidates,
)
from meridian.loader.policy_corpus import POLICY_CORPUS_V1

# -----------------------------------------------------------------------------
# Part 1: Pure Python Tests
# -----------------------------------------------------------------------------


def _invoke_rrf(
    lexical_ranks: Dict[Any, int],
    semantic_ranks: Dict[Any, int],
    metadata: Dict[Any, Dict[str, Any]],
    k: int = 60,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Helper to invoke reciprocal_rank_fusion if available, or simulate old retrieval."""
    try:
        from meridian.agents.policy.retrieval import reciprocal_rank_fusion

        return reciprocal_rank_fusion(
            lexical_ranks=lexical_ranks,
            semantic_ranks=semantic_ranks,
            metadata=metadata,
            k=k,
            top_k=top_k,
        )
    except ImportError:
        # Fallback simulating old logic in retrieval.py lines 113-135
        rrf_scores: Dict[Any, float] = {}
        all_chunk_ids = set(lexical_ranks.keys()).union(set(semantic_ranks.keys()))

        for chunk_id in all_chunk_ids:
            score = 0.0
            if chunk_id in lexical_ranks:
                score += 1.0 / (k + lexical_ranks[chunk_id])
            if chunk_id in semantic_ranks:
                score += 1.0 / (k + semantic_ranks[chunk_id])
            rrf_scores[chunk_id] = score

        sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
        top_candidates = sorted_chunks[:top_k]

        results = []
        for chunk_id, score in top_candidates:
            candidate = metadata[chunk_id].copy()
            candidate["rrf_score"] = score
            results.append(candidate)

        return results


def test_rrf_equal_scores_logical_ordering_key() -> None:
    """Equal fused scores resolve according to the complete logical ordering key.

    Ordering key:
        1. Primary score: descending
        2. Document title: ascending (COLLATE "C")
        3. Document version: ascending
        4. Chunk index: ascending
        5. Chunk ID: ascending
    """
    id1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
    id2 = uuid.UUID("00000000-0000-0000-0000-000000000002")
    id3 = uuid.UUID("00000000-0000-0000-0000-000000000003")

    # All three chunks have identical ranks in both paths -> identical RRF score
    lexical_ranks = {id1: 1, id2: 1, id3: 1}
    semantic_ranks = {id1: 1, id2: 1, id3: 1}

    metadata = {
        id1: {
            "chunk_id": id1,
            "document_id": uuid.uuid4(),
            "title": "Beta Policy",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Chunk from Beta",
        },
        id2: {
            "chunk_id": id2,
            "document_id": uuid.uuid4(),
            "title": "Alpha Policy",
            "document_type": "internal_policy",
            "version": "v2",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Chunk from Alpha v2",
        },
        id3: {
            "chunk_id": id3,
            "document_id": uuid.uuid4(),
            "title": "Alpha Policy",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Chunk from Alpha v1",
        },
    }

    # Expected order:
    # 1. "Alpha Policy", "v1", 0 (id3)
    # 2. "Alpha Policy", "v2", 0 (id2)
    # 3. "Beta Policy",  "v1", 0 (id1)
    results = _invoke_rrf(lexical_ranks, semantic_ranks, metadata, k=60, top_k=3)

    assert [r["chunk_id"] for r in results] == [id3, id2, id1]


def test_rrf_tie_at_top_k_boundary() -> None:
    """A tie at the top-k boundary selects the expected logical chunks."""
    id_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    id_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
    id_c = uuid.UUID("00000000-0000-0000-0000-000000000003")

    lexical_ranks = {id_a: 1, id_b: 2, id_c: 2}
    semantic_ranks = {id_a: 1, id_b: 2, id_c: 2}

    metadata = {
        id_a: {
            "chunk_id": id_a,
            "document_id": uuid.uuid4(),
            "title": "Clear Winner",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Text A",
        },
        id_b: {
            "chunk_id": id_b,
            "document_id": uuid.uuid4(),
            "title": "Tied Second - Z",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Text B",
        },
        id_c: {
            "chunk_id": id_c,
            "document_id": uuid.uuid4(),
            "title": "Tied Second - A",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Text C",
        },
    }

    # Request top_k = 2.
    # Winner: id_a (highest score)
    # Runner up tied: id_c ("Tied Second - A") vs id_b ("Tied Second - Z").
    # Total ordering requires id_c to be selected over id_b.
    results = _invoke_rrf(lexical_ranks, semantic_ranks, metadata, k=60, top_k=2)

    assert len(results) == 2
    assert results[0]["chunk_id"] == id_a
    assert results[1]["chunk_id"] == id_c


def test_rrf_permutation_invariance() -> None:
    """Permuting equivalent input dictionary insertion orders produces identical output."""
    ids = [uuid.UUID(f"00000000-0000-0000-0000-{i:012d}") for i in range(1, 6)]

    metadata = {
        cid: {
            "chunk_id": cid,
            "document_id": uuid.uuid4(),
            "title": f"Doc {5 - i}",  # Inverted title order
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": f"Text {i}",
        }
        for i, cid in enumerate(ids)
    }

    # All equal scores
    ranks_forward = {cid: 1 for cid in ids}
    ranks_reversed = {cid: 1 for cid in reversed(ids)}

    res1 = _invoke_rrf(ranks_forward, ranks_forward, metadata, k=60, top_k=5)
    res2 = _invoke_rrf(ranks_reversed, ranks_reversed, metadata, k=60, top_k=5)

    assert [r["chunk_id"] for r in res1] == [r["chunk_id"] for r in res2]


def test_python_sql_collate_c_comparator_agreement(app_role_engine: Engine) -> None:
    """The Python comparator agrees with verified SQL COLLATE "C" semantics for representative strings."""
    test_strings = [
        "Apple",
        "apple",
        "BANANA",
        "banana",
        "123",
        "456",
        "",
        "   ",
        "Zebra",
        "aardvark",
        "São Paulo",
        "München",
        "Tokyo",
        "— em dash",
        "- hyphen",
        "naïve",
        "resume",
        "résumé",
        "Synthetic Internal Policy — Large / unusual transaction review procedure",
        "Synthetic Internal Policy — New beneficiary review procedure",
        "Synthetic Internal Policy — Rapid movement of funds review procedure",
        "Synthetic Internal Policy — Investigation evidence and documentation standards",
        "v1",
        "v1.0",
        "v2",
        "v0.5",
        "\u00a0non-breaking",
        " non-breaking",
    ]

    with app_role_engine.connect() as conn:
        sql = sa.text(
            'SELECT val FROM (SELECT unnest(cast(:arr as text[])) as val) t ORDER BY val COLLATE "C" ASC'
        )
        db_sorted = [r[0] for r in conn.execute(sql, {"arr": test_strings}).fetchall()]

    py_sorted = sorted(test_strings)
    assert db_sorted == py_sorted


def test_public_result_shape_preserved() -> None:
    """Public result field names and types remain unchanged."""
    cid = uuid.uuid4()
    did = uuid.uuid4()
    metadata = {
        cid: {
            "chunk_id": cid,
            "document_id": did,
            "title": "Title",
            "document_type": "internal_policy",
            "version": "v1",
            "is_synthetic": True,
            "chunk_index": 0,
            "chunk_text": "Text",
        }
    }
    results = _invoke_rrf({cid: 1}, {cid: 1}, metadata, k=60, top_k=1)
    assert len(results) == 1
    r = results[0]
    expected_keys = {
        "chunk_id",
        "document_id",
        "title",
        "document_type",
        "version",
        "is_synthetic",
        "chunk_index",
        "chunk_text",
        "rrf_score",
    }
    assert set(r.keys()) == expected_keys
    assert isinstance(r["chunk_id"], uuid.UUID)
    assert isinstance(r["document_id"], uuid.UUID)
    assert isinstance(r["title"], str)
    assert isinstance(r["document_type"], str)
    assert isinstance(r["version"], str)
    assert isinstance(r["is_synthetic"], bool)
    assert isinstance(r["chunk_index"], int)
    assert isinstance(r["chunk_text"], str)
    assert isinstance(r["rrf_score"], float)


def test_rrf_missing_or_invalid_metadata_fails_clearly() -> None:
    """Missing or invalid required metadata (title, version, chunk_index) fails clearly without silent defaults."""
    cid = uuid.uuid4()
    ranks = {cid: 1}

    # Missing title raises KeyError
    meta_no_title = {cid: {"version": "v1", "chunk_index": 0}}
    with pytest.raises(KeyError):
        _invoke_rrf(ranks, ranks, meta_no_title)

    # Missing version raises KeyError
    meta_no_version = {cid: {"title": "Title", "chunk_index": 0}}
    with pytest.raises(KeyError):
        _invoke_rrf(ranks, ranks, meta_no_version)

    # Missing chunk_index raises KeyError
    meta_no_chunk_index = {cid: {"title": "Title", "version": "v1"}}
    with pytest.raises(KeyError):
        _invoke_rrf(ranks, ranks, meta_no_chunk_index)

    # None chunk_index raises TypeError in int()
    meta_none_chunk_index = {
        cid: {"title": "Title", "version": "v1", "chunk_index": None}
    }
    with pytest.raises(TypeError):
        _invoke_rrf(ranks, ranks, meta_none_chunk_index)

    # Invalid non-integer chunk_index raises ValueError in int()
    meta_invalid_chunk_index = {
        cid: {"title": "Title", "version": "v1", "chunk_index": "not_an_int"}
    }
    with pytest.raises(ValueError):
        _invoke_rrf(ranks, ranks, meta_invalid_chunk_index)


def test_policy_corpus_uniqueness() -> None:
    """The built-in policy corpus's (title, version, chunk_index) tuples are verified unique.

    Note: This is an application-level invariant of the built-in corpus and chunker,
    not a database schema constraint.
    """
    seen = set()
    total = 0
    for doc in POLICY_CORPUS_V1:
        chunks = chunk_document(doc.text)
        for idx, _ in enumerate(chunks):
            key = (doc.title, doc.version, idx)
            assert key not in seen, f"Duplicate tuple detected in corpus: {key}"
            seen.add(key)
            total += 1
    assert total > 0


# -----------------------------------------------------------------------------
# Part 2: Disposable Database Tests
# -----------------------------------------------------------------------------


def test_lexical_equal_scores_deterministic_ordering(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Equal lexical scores produce the expected deterministic order across repeated calls."""
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    doc_id1 = uuid.uuid4()
    doc_id2 = uuid.uuid4()

    # Create two documents with different titles
    with loader_role_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                "VALUES (:id1, 'B_Policy', 'internal_policy', 'v1', true), "
                "       (:id2, 'A_Policy', 'internal_policy', 'v1', true)"
            ),
            {"id1": str(doc_id1), "id2": str(doc_id2)},
        )
        # Chunks with identical chunk_text so ts_rank_cd produces exact identical score
        cid_b = uuid.UUID("00000000-0000-0000-0000-000000000002")
        cid_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
        conn.execute(
            sa.text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                "VALUES (:cid_b, :did1, 'exact identical peculiar keyword xyzzy', 0, cast(:emb as vector(384))), "
                "       (:cid_a, :did2, 'exact identical peculiar keyword xyzzy', 0, cast(:emb as vector(384)))"
            ),
            {
                "cid_b": str(cid_b),
                "did1": str(doc_id1),
                "cid_a": str(cid_a),
                "did2": str(doc_id2),
                "emb": str([0.0] * 384),
            },
        )

    with Session(app_role_engine) as session:
        for _ in range(3):
            candidates = retrieve_candidates(session, "xyzzy", k=60, top_k=2)
            assert len(candidates) == 2
            # Total order must place "A_Policy" before "B_Policy"
            assert candidates[0]["title"] == "A_Policy"
            assert candidates[0]["chunk_id"] == cid_a
            assert candidates[1]["title"] == "B_Policy"
            assert candidates[1]["chunk_id"] == cid_b


def test_vector_equal_distance_deterministic_ordering(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Equal vector distances produce the expected deterministic order across repeated calls."""
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    doc_id1 = uuid.uuid4()
    doc_id2 = uuid.uuid4()

    with loader_role_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                "VALUES (:id1, 'Z_Doc', 'internal_policy', 'v1', true), "
                "       (:id2, 'M_Doc', 'internal_policy', 'v1', true)"
            ),
            {"id1": str(doc_id1), "id2": str(doc_id2)},
        )
        # Identical embeddings -> distance is identical
        cid_z = uuid.UUID("00000000-0000-0000-0000-000000000002")
        cid_m = uuid.UUID("00000000-0000-0000-0000-000000000001")
        conn.execute(
            sa.text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                "VALUES (:cid_z, :did1, 'random text one', 0, cast(:emb as vector(384))), "
                "       (:cid_m, :did2, 'random text two', 0, cast(:emb as vector(384)))"
            ),
            {
                "cid_z": str(cid_z),
                "did1": str(doc_id1),
                "cid_m": str(cid_m),
                "did2": str(doc_id2),
                "emb": str([0.1] * 384),
            },
        )

    with Session(app_role_engine) as session:
        for _ in range(3):
            # Query that matches neither lexically -> pure semantic sort
            candidates = retrieve_candidates(
                session, "query with no lexical overlap whatsoever", k=60, top_k=2
            )
            assert len(candidates) == 2
            # M_Doc must precede Z_Doc
            assert candidates[0]["title"] == "M_Doc"
            assert candidates[0]["chunk_id"] == cid_m
            assert candidates[1]["title"] == "Z_Doc"
            assert candidates[1]["chunk_id"] == cid_z


def test_equivalent_data_different_insertion_order(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Equivalent logical data inserted in different orders produces the same logical result order."""
    doc_specs = [
        ("Policy Charlie", "v1", 0, "common keyword topic text"),
        ("Policy Alpha", "v1", 0, "common keyword topic text"),
        ("Policy Bravo", "v1", 0, "common keyword topic text"),
    ]

    def _insert_and_retrieve(order_indices: List[int]) -> List[str]:
        with superuser_engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

        with loader_role_engine.begin() as conn:
            for i in order_indices:
                title, ver, c_idx, text = doc_specs[i]
                did = uuid.uuid4()
                cid = uuid.uuid4()
                conn.execute(
                    sa.text(
                        "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                        "VALUES (:did, :t, 'internal_policy', :v, true)"
                    ),
                    {"did": str(did), "t": title, "v": ver},
                )
                conn.execute(
                    sa.text(
                        "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                        "VALUES (:cid, :did, :text, :c_idx, cast(:emb as vector(384)))"
                    ),
                    {
                        "cid": str(cid),
                        "did": str(did),
                        "text": text,
                        "c_idx": c_idx,
                        "emb": str([0.05] * 384),
                    },
                )

        with Session(app_role_engine) as session:
            res = retrieve_candidates(session, "keyword", k=60, top_k=3)
            return [r["title"] for r in res]

    # Insert in order [0, 1, 2] vs [2, 0, 1]
    res1 = _insert_and_retrieve([0, 1, 2])
    res2 = _insert_and_retrieve([2, 0, 1])

    assert res1 == ["Policy Alpha", "Policy Bravo", "Policy Charlie"]
    assert res2 == ["Policy Alpha", "Policy Bravo", "Policy Charlie"]


def test_corpus_reload_logical_stability_g2(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Reloading the same logical corpus with new UUID4 identifiers preserves logical ordering (G2)."""

    def _load_corpus() -> None:
        with superuser_engine.begin() as conn:
            conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

        with loader_role_engine.begin() as conn:
            for doc in POLICY_CORPUS_V1:
                did = uuid.uuid4()  # New UUID4
                conn.execute(
                    sa.text(
                        "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                        "VALUES (:did, :title, :dtype, :version, true)"
                    ),
                    {
                        "did": str(did),
                        "title": doc.title,
                        "dtype": doc.document_type,
                        "version": doc.version,
                    },
                )
                chunks = chunk_document(doc.text)
                for idx, ctext in enumerate(chunks):
                    cid = uuid.uuid4()  # New UUID4
                    emb = embed_document_chunk(ctext)
                    conn.execute(
                        sa.text(
                            "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                            "VALUES (:cid, :did, :text, :idx, cast(:emb as vector(384)))"
                        ),
                        {
                            "cid": str(cid),
                            "did": str(did),
                            "text": ctext,
                            "idx": idx,
                            "emb": str(emb),
                        },
                    )

    # First load
    _load_corpus()
    with Session(app_role_engine) as session:
        run1 = retrieve_candidates(session, "large transaction review", top_k=4)
        run1_identities = [(r["title"], r["version"], r["chunk_index"]) for r in run1]
        run1_ids = [r["chunk_id"] for r in run1]

    # Second load (reloaded with fresh UUIDs)
    _load_corpus()
    with Session(app_role_engine) as session:
        run2 = retrieve_candidates(session, "large transaction review", top_k=4)
        run2_identities = [(r["title"], r["version"], r["chunk_index"]) for r in run2]
        run2_ids = [r["chunk_id"] for r in run2]

    # G2 Guarantee: logical result identities are strictly stable
    assert run1_identities == run2_identities
    # UUID4s are NOT expected to be equal across reloads
    assert run1_ids != run2_ids


def test_duplicate_logical_tuples_fixed_db_determinism(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Duplicate logical identity tuples remain repeatable within a fixed DB state via chunk ID (G1)."""
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    did = uuid.uuid4()
    # Fixed chunk IDs to test chunk ID ordering
    cid_low = uuid.UUID("00000000-0000-0000-0000-000000000001")
    cid_high = uuid.UUID("00000000-0000-0000-0000-000000000002")

    with loader_role_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                "VALUES (:did, 'Duplicate Doc', 'internal_policy', 'v1', true)"
            ),
            {"did": str(did)},
        )
        # Identical title, version, chunk_index, and text, differing only by chunk_id
        conn.execute(
            sa.text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                "VALUES (:c2, :did, 'identical text content', 0, cast(:emb as vector(384))), "
                "       (:c1, :did, 'identical text content', 0, cast(:emb as vector(384)))"
            ),
            {
                "c2": str(cid_high),
                "c1": str(cid_low),
                "did": str(did),
                "emb": str([0.1] * 384),
            },
        )

    with Session(app_role_engine) as session:
        res1 = retrieve_candidates(session, "identical text content", top_k=2)
        res2 = retrieve_candidates(session, "identical text content", top_k=2)

        # Within fixed DB state, repeated queries yield identical chunk_id ordering
        assert [r["chunk_id"] for r in res1] == [cid_low, cid_high]
        assert [r["chunk_id"] for r in res2] == [cid_low, cid_high]


def test_lexical_join_preservation(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Lexical join-preservation test compares pre-change and post-change row sets."""
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    did = uuid.uuid4()
    with loader_role_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                "VALUES (:did, 'Test Doc', 'internal_policy', 'v1', true)"
            ),
            {"did": str(did)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                "VALUES (gen_random_uuid(), :did, 'sample chunk with testquery token', 0, cast(:emb as vector(384)))"
            ),
            {"did": str(did), "emb": str([0.0] * 384)},
        )

    with app_role_engine.connect() as conn:
        # Pre-change query (without join)
        pre_sql = sa.text(
            """
            SELECT c.chunk_id
            FROM document_chunks c
            WHERE to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', 'testquery')
            """
        )
        pre_rows = set(r[0] for r in conn.execute(pre_sql).fetchall())

        # Post-change query (with inner join)
        post_sql = sa.text(
            """
            SELECT c.chunk_id
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.document_id
            WHERE to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', 'testquery')
            """
        )
        post_rows = set(r[0] for r in conn.execute(post_sql).fetchall())

        assert len(pre_rows) > 0
        assert pre_rows == post_rows


def test_policy_agent_evidence_preservation(
    loader_role_engine: Engine, app_role_engine: Engine, superuser_engine: Engine
) -> None:
    """Verifies that retrieve_policy_evidence preserves threshold and typing behavior."""
    with superuser_engine.begin() as conn:
        conn.execute(sa.text("TRUNCATE document_chunks, documents CASCADE"))

    did = uuid.uuid4()
    with loader_role_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO documents (document_id, title, document_type, version, is_synthetic) "
                "VALUES (:did, 'Anti-Money Laundering Policy', 'internal_policy', 'v1', true)"
            ),
            {"did": str(did)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO document_chunks (chunk_id, document_id, chunk_text, chunk_index, embedding) "
                "VALUES (gen_random_uuid(), :did, 'specific text on structuring and smurfing', 0, cast(:emb as vector(384)))"
            ),
            {"did": str(did), "emb": str([0.1] * 384)},
        )

    with Session(app_role_engine) as session:
        # 1. Above threshold -> PolicyEvidenceFound
        found = retrieve_policy_evidence(
            session, "structuring and smurfing", confidence_threshold=0.01
        )
        assert isinstance(found, PolicyEvidenceFound)
        assert len(found.citations) == 1
        assert found.citations[0].title == "Anti-Money Laundering Policy"
        assert found.citations[0].version == "v1"

        # 2. Impossibly high threshold -> PolicyEvidenceInsufficient
        insufficient = retrieve_policy_evidence(
            session, "structuring and smurfing", confidence_threshold=1.0
        )
        assert isinstance(insufficient, PolicyEvidenceInsufficient)
