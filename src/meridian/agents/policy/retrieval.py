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


def retrieve_candidates(
    session: Session, query: str, k: int = 60, top_k: int = 5
) -> List[Dict[str, Any]]:
    """
    Retrieves policy chunk candidates using a hybrid search:
    PostgreSQL FTS (lexical) + pgvector EXACT cosine distance (semantic),
    fused via Reciprocal Rank Fusion (RRF) over complete corpus-wide rankings.

    Status: PROPOSAL-level default for k=60 and K=5.

    No candidate-pool cutoff before fusion.
    Returns: list of dicts with keys: chunk_id, document_id, title, document_type,
             version, is_synthetic, chunk_index, rrf_score
    """

    query_embedding = embed_query(query)

    # 1. Lexical Path (FTS)
    # COMPLETE ranked list over the ENTIRE corpus.
    lexical_sql = sa.text(
        """
        SELECT
            c.chunk_id,
            ts_rank_cd(
                to_tsvector('english', c.chunk_text),
                plainto_tsquery('english', :query)
            ) as lexical_score
        FROM document_chunks c
        WHERE to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', :query)
        ORDER BY lexical_score DESC
        """
    )
    lexical_results = session.execute(lexical_sql, {"query": query}).fetchall()

    # Rank mapping (1-based)
    lexical_ranks = {
        row.chunk_id: rank for rank, row in enumerate(lexical_results, start=1)
    }

    # 2. Semantic Path (pgvector)
    # EXACT pgvector cosine-distance scan against every chunk's embedding.
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
        ORDER BY c.embedding <=> cast(:embedding as vector(384)) ASC
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

    # 3. Reciprocal Rank Fusion (RRF) over the two COMPLETE lists
    rrf_scores = {}
    all_chunk_ids = set(lexical_ranks.keys()).union(set(semantic_ranks.keys()))

    for chunk_id in all_chunk_ids:
        score = 0.0
        if chunk_id in lexical_ranks:
            score += 1.0 / (k + lexical_ranks[chunk_id])
        if chunk_id in semantic_ranks:
            score += 1.0 / (k + semantic_ranks[chunk_id])
        rrf_scores[chunk_id] = score

    # 4. Truncate to top-K ONLY AFTER fusion
    sorted_chunks = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    top_candidates = sorted_chunks[:top_k]

    # Build final result
    results = []
    for chunk_id, score in top_candidates:
        candidate = metadata[chunk_id].copy()
        candidate["rrf_score"] = score
        results.append(candidate)

    return results
