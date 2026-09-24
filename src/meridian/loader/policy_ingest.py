# ruff: noqa: E501
import uuid
from typing import Sequence, Tuple

from sqlalchemy import Engine, text

from meridian.loader.policy_corpus import POLICY_CORPUS_V1, PolicyDocumentSpec


def ingest_policy_corpus(
    engine: Engine,
    corpus: Sequence[PolicyDocumentSpec] = POLICY_CORPUS_V1,
) -> Tuple[int, int]:
    """
    Ingests the synthetic policy corpus into the documents and document_chunks tables.

    Inputs:
        engine: The loader role database engine.
        corpus: The sequence of PolicyDocumentSpec objects to ingest.

    Outputs:
        A tuple of (documents_inserted, chunks_inserted).

    Side effects:
        Inserts data into 'documents' and 'document_chunks' tables in a single transaction.

    Failure modes:
        Raises ValueError if a document is not synthetic, not internal_policy, or produces 0 chunks.
        Raises sqlalchemy.exc.SQLAlchemyError for database issues, rolling back the transaction.
    """
    # Import chunking/embedding here to avoid model loading on module import
    from meridian.agents.policy.chunking import chunk_document
    from meridian.agents.policy.retrieval import embed_document_chunk

    docs_inserted = 0
    chunks_inserted = 0

    # Validation pass
    for doc in corpus:
        if not doc.is_synthetic:
            raise ValueError(f"Document '{doc.title}' must be synthetic.")
        if doc.document_type != "internal_policy":
            raise ValueError(f"Document '{doc.title}' must have document_type 'internal_policy'.")

        chunks_text = chunk_document(doc.text)
        if not chunks_text:
            raise ValueError(f"Document '{doc.title}' produced zero chunks.")

    with engine.begin() as conn:
        for doc in corpus:
            doc_id = str(uuid.uuid4())

            conn.execute(
                text(
                    "INSERT INTO documents "
                    "(document_id, title, document_type, version, source_url_or_ref, is_synthetic) "
                    "VALUES (:doc_id, :title, :document_type, :version, :source_url_or_ref, :is_synthetic)"
                ),
                {
                    "doc_id": doc_id,
                    "title": doc.title,
                    "document_type": doc.document_type,
                    "version": doc.version,
                    "source_url_or_ref": doc.source_url_or_ref,
                    "is_synthetic": doc.is_synthetic,
                }
            )
            docs_inserted += 1

            chunks_text = chunk_document(doc.text)
            for idx, c_text in enumerate(chunks_text):
                chunk_id = str(uuid.uuid4())
                embedding = embed_document_chunk(c_text)

                conn.execute(
                    text(
                        "INSERT INTO document_chunks "
                        "(chunk_id, document_id, chunk_text, chunk_index, embedding) "
                        "VALUES (:chunk_id, :doc_id, :chunk_text, :chunk_index, cast(:embedding as vector(384)))"
                    ),
                    {
                        "chunk_id": chunk_id,
                        "doc_id": doc_id,
                        "chunk_text": c_text,
                        "chunk_index": idx,
                        "embedding": str(embedding),
                    }
                )
                chunks_inserted += 1

    return docs_inserted, chunks_inserted
