from typing import Any, Dict, List, cast

import sqlalchemy as sa
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session

# Load the model locally. CPU only.
# This will trigger a download on first run if not cached.
# Model inference uses NO external embedding API and NO API key.
# Dimension: 384
embedding_model = SentenceTransformer("BAAI/bge-small-en-v1.5")


def embed_document_chunk(chunk_text: str) -> List[float]:
    """
    Embeds a document chunk for storage.
    As per locking, NO instruction prefix is added.
    """
    res = embedding_model.encode(chunk_text, normalize_embeddings=True).tolist()
    return cast(List[float], res)


def embed_query(query: str) -> List[float]:
    """
    Embeds a query for searching.
    As per locking, EXACT instruction prefix is added:
    'Represent this sentence for searching relevant passages: {query}'
    """
    instruction = f"Represent this sentence for searching relevant passages: {query}"
    res = embedding_model.encode(instruction, normalize_embeddings=True).tolist()
    return cast(List[float], res)


def reciprocal_rank_fusion(
    lexical_ranks: Dict[Any, int],
    semantic_ranks: Dict[Any, int],
    metadata: Dict[Any, Dict[str, Any]],
    k: int = 60,
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """
    Combines rank mappings via Reciprocal Rank Fusion (RRF) with deterministic
    total ordering.

    Ordering contract:
        1. Primary score: RRF score descending.
        2. Document title: ascending (matching SQL COLLATE "C").
        3. Document version: ascending (matching SQL COLLATE "C").
        4. Chunk index: ascending.
        5. Chunk ID: ascending (string representation as final tie-breaker).

    Guarantees:
        G1 (Fixed-database determinism): Repeatable ordering for fixed DB state
        and inputs.
        G2 (Conditional reload stability): Stable logical ordering across reloads
        if (title, version, chunk_index) uniquely identifies each logical chunk
        and all scoring inputs and retrieval configuration remain equivalent.

    Limitations:
        Does not guarantee determinism across differing corpora, model revisions,
        or modified retrieval configurations.
    """
    rrf_scores: Dict[Any, float] = {}
    all_chunk_ids = set(lexical_ranks.keys()).union(set(semantic_ranks.keys()))

    for chunk_id in all_chunk_ids:
        score = 0.0
        if chunk_id in lexical_ranks:
            score += 1.0 / (k + lexical_ranks[chunk_id])
        if chunk_id in semantic_ranks:
            score += 1.0 / (k + semantic_ranks[chunk_id])
        rrf_scores[chunk_id] = score

    # Deterministic total order
    sorted_chunk_ids = sorted(
        all_chunk_ids,
        key=lambda cid: (
            -rrf_scores[cid],
            metadata[cid]["title"],
            metadata[cid]["version"],
            int(metadata[cid]["chunk_index"]),
            str(cid),
        ),
    )
    top_candidates = sorted_chunk_ids[:top_k]

    results = []
    for chunk_id in top_candidates:
        candidate = metadata[chunk_id].copy()
        candidate["rrf_score"] = rrf_scores[chunk_id]
        results.append(candidate)

    return results


def retrieve_candidates(
    session: Session, query: str, k: int = 60, top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Retrieves policy chunk candidates using a hybrid search:
    PostgreSQL FTS (lexical) + pgvector EXACT cosine distance (semantic),
    fused via Reciprocal Rank Fusion (RRF) with deterministic total ordering.

    Ordering contract for each stage:
        1. Primary score: descending for lexical and fused RRF; ascending for
           vector distance.
        2. Document title: ascending (SQL COLLATE "C").
        3. Document version: ascending (SQL COLLATE "C").
        4. Chunk index: ascending.
        5. Chunk ID: ascending (final tie-breaker).

    Guarantees:
        G1 (Fixed-database determinism): Output is strictly deterministic for
        fixed database state.
        G2 (Conditional reload stability): Logical ordering is preserved across
        reloads when (title, version, chunk_index) uniquely identifies logical
        chunks and scoring inputs are identical.

    Limitations:
        Does not guarantee stability across changed corpora, differing model
        weights, or altered config.

    No candidate-pool cutoff before fusion.
    Returns: list of dicts with keys: chunk_id, document_id, title, document_type,
             version, is_synthetic, chunk_index, rrf_score
    """

    query_embedding = embed_query(query)

    # 1. Lexical Path (FTS)
    # COMPLETE ranked list over ENTIRE corpus with deterministic total ordering.
    lexical_sql = sa.text(
        """
        SELECT
            c.chunk_id,
            d.title,
            d.document_type,
            d.version,
            d.is_synthetic,
            c.document_id,
            c.chunk_index,
            c.chunk_text,
            ts_rank_cd(
                to_tsvector('english', c.chunk_text),
                plainto_tsquery('english', :query)
            ) as lexical_score
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.document_id
        WHERE to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', :query)
        ORDER BY
            lexical_score DESC,
            d.title COLLATE "C" ASC,
            d.version COLLATE "C" ASC,
            c.chunk_index ASC,
            c.chunk_id ASC
        """
    )
    lexical_results = session.execute(lexical_sql, {"query": query}).fetchall()

    # Rank mapping (1-based)
    lexical_ranks = {
        row.chunk_id: rank for rank, row in enumerate(lexical_results, start=1)
    }

    # 2. Semantic Path (pgvector)
    # EXACT pgvector cosine-distance scan against every chunk's embedding
    # with deterministic total ordering.
    semantic_sql = sa.text(
        """
        SELECT
            c.chunk_id,
            d.title,
            d.document_type,
            d.version,
            d.is_synthetic,
            c.document_id,
            c.chunk_index,
            c.chunk_text
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.document_id
        ORDER BY
            c.embedding <=> cast(:embedding as vector(384)) ASC,
            d.title COLLATE "C" ASC,
            d.version COLLATE "C" ASC,
            c.chunk_index ASC,
            c.chunk_id ASC
        """
    )
    semantic_results = session.execute(
        semantic_sql, {"embedding": str(query_embedding)}
    ).fetchall()

    semantic_ranks = {
        row.chunk_id: rank for rank, row in enumerate(semantic_results, start=1)
    }

    metadata = {}
    for row in semantic_results:
        metadata[row.chunk_id] = {
            "chunk_id": row.chunk_id,
            "document_id": row.document_id,
            "title": row.title,
            "document_type": row.document_type,
            "version": row.version,
            "is_synthetic": row.is_synthetic,
            "chunk_index": row.chunk_index,
            "chunk_text": row.chunk_text,
        }
    for row in lexical_results:
        if row.chunk_id not in metadata:
            metadata[row.chunk_id] = {
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "title": row.title,
                "document_type": row.document_type,
                "version": row.version,
                "is_synthetic": row.is_synthetic,
                "chunk_index": row.chunk_index,
                "chunk_text": row.chunk_text,
            }

    # 3. Reciprocal Rank Fusion (RRF) with deterministic total ordering
    return reciprocal_rank_fusion(
        lexical_ranks=lexical_ranks,
        semantic_ranks=semantic_ranks,
        metadata=metadata,
        k=k,
        top_k=top_k,
    )
