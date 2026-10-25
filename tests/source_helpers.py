"""Real source rows for tests that mock agent computation, not data integrity."""

import uuid

from sqlalchemy import Engine, text


def seed_source(engine: Engine, table: str) -> uuid.UUID:
    source_id = uuid.uuid4()
    with engine.begin() as conn:
        if table == "transactions":
            conn.execute(text(
                "INSERT INTO transactions (transaction_id, amount, currency) "
                "VALUES (:id, 10, 'INR')"
            ), {"id": source_id})
        elif table == "document_chunks":
            doc = uuid.uuid4()
            conn.execute(text(
                "INSERT INTO documents (document_id, title, document_type, "
                "version, is_synthetic) VALUES (:id, 'integrity-test', "
                "'internal_policy', 'v1', true)"
            ), {"id": doc})
            conn.execute(text(
                "INSERT INTO document_chunks (chunk_id, document_id, "
                "chunk_text, chunk_index) VALUES (:id, :doc, 'Test policy', 0)"
            ), {"id": source_id, "doc": doc})
        elif table == "watchlist_entries":
            conn.execute(text(
                "INSERT INTO watchlist_entries (entry_id, watchlist_name, "
                "watchlist_version, subject_key, name_type, listed_name, "
                "is_synthetic, source) VALUES (:id, 'integrity-test', 'v1', "
                ":subject, 'primary', 'Synthetic Reference', true, 'test')"
            ), {"id": source_id, "subject": str(source_id)})
        else:
            raise ValueError("Unsupported test source")
    return source_id


def cleanup_reference_sources(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM document_chunks WHERE document_id IN "
                          "(SELECT document_id FROM documents "
                          "WHERE title = 'integrity-test')"))
        conn.execute(text("DELETE FROM documents WHERE title = 'integrity-test'"))
        conn.execute(text("DELETE FROM watchlist_entries "
                          "WHERE watchlist_name = 'integrity-test'"))


def empty_graph_execution(*args: object, **kwargs: object):
    """A valid zero-edge graph result for tests of other agent wiring."""
    from meridian.agents.graph.structure_signals import (
        ChainDepthComputed,
        CycleNotFound,
    )
    from meridian.agents.graph.subgraph import SubgraphResult
    from meridian.orchestration.graph_agent_dispatch import GraphAgentExecutionResult

    account_id = kwargs.get("account_id", args[1] if len(args) > 1 else uuid.uuid4())
    return GraphAgentExecutionResult(
        subgraph=SubgraphResult(
            start_entity_id=account_id, max_hops=3, node_entity_ids=(account_id,),
            relationship_ids=(), truncated=False,
        ),
        cycle=CycleNotFound(account_id=account_id),
        chain=ChainDepthComputed(
            account_id=account_id, depth=0, chain_entity_ids=(),
            chain_relationship_ids=(),
        ),
    )
