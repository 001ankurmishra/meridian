"""Run the approved v2 baseline using native retrieval in temporary DB tables."""

import argparse
import hashlib
import json
import math
import os
import statistics
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from meridian.evaluation.external.ibm import sha256_file
from meridian.testing.guard import verify_test_database_safety


def approved_protocol(directory: Path, corpus: Path) -> dict[str, Any]:
    protocol: dict[str, Any] = json.loads(
        (directory / "retrieval-review.json").read_text()
    )
    freeze = json.loads((directory / "retrieval-freeze.json").read_text())
    digest = hashlib.sha256(
        json.dumps(
            protocol,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    if (
        freeze["status"] != "FROZEN"
        or freeze["approved_review_sha256"] != digest
        or sha256_file(corpus) != freeze["corpus_sha256"]
        or protocol["corpus_sha256"] != freeze["corpus_sha256"]
    ):
        raise ValueError("Approved protocol/corpus freeze mismatch")
    return protocol


def query_metrics(actual: list[str], relevant: list[str]) -> dict[str, Any]:
    gains = [int(cid in relevant) for cid in actual[:5]]
    hits = sum(gains)
    dcg = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(5, len(relevant))))
    return {
        "precision_at_5": hits / 5,
        "recall_at_5": hits / len(relevant) if relevant else None,
        "mrr_at_5": next((1 / (i + 1) for i, gain in enumerate(gains) if gain), 0),
        "ndcg_at_5": dcg / ideal if ideal else None,
        "abstained": not actual,
    }


def run(directory: Path, corpus: Path, output: Path) -> dict[str, Any]:
    protocol = approved_protocol(directory, corpus)
    if output.exists() or output.with_suffix(".started.json").exists():
        raise FileExistsError("Measurement already started; inspect existing evidence")
    verify_test_database_safety()
    # Explicit imports only after approval and disposable-database checks.
    from meridian.agents.policy.model_config import MODEL_NAME, MODEL_REVISION
    from meridian.agents.policy.policy_agent import (
        PolicyEvidenceFound,
        retrieve_policy_evidence,
    )
    from meridian.agents.policy.retrieval import embedding_model

    with output.with_suffix(".started.json").open("x") as receipt:
        receipt.write(
            json.dumps({"status": "STARTED", "corpus_sha256": sha256_file(corpus)})
        )
    records = [json.loads(line) for line in corpus.read_text().splitlines()]
    logical = {str(uuid.uuid5(uuid.NAMESPACE_URL, r["chunk_id"])): r for r in records}
    if len(logical) != len(records):
        raise ValueError("Duplicate corpus IDs")
    known = {r["chunk_id"] for r in records}
    for query in protocol["queries"]:
        if not set(query["expected_relevant_chunks"]) <= known:
            raise ValueError("Unknown labeled chunk")
    start = time.monotonic()
    vectors = embedding_model.encode(
        [r["text"] for r in records],
        normalize_embeddings=True,
        batch_size=32,
        show_progress_bar=False,
    ).tolist()
    embedding_seconds = time.monotonic() - start
    engine = create_engine(os.environ["APP_DATABASE_URL"], hide_parameters=True)
    measured = []
    try:
        with engine.begin() as connection:
            # pg_temp shadows public tables for this session only. The runtime role
            # has TEMP permission but no permission to mutate persisted references.
            connection.execute(
                text("""
                CREATE TEMP TABLE documents (
                    document_id uuid, title text, document_type text,
                    version text, is_synthetic boolean
                ) ON COMMIT DROP
            """)
            )
            connection.execute(
                text("""
                CREATE TEMP TABLE document_chunks (
                    chunk_id uuid, document_id uuid, chunk_index integer,
                    chunk_text text, embedding vector(384)
                ) ON COMMIT DROP
            """)
            )
            documents = {r["source_id"]: r for r in records}
            for source, r in documents.items():
                connection.execute(
                    text("""
                    INSERT INTO documents VALUES (:id, :title, 'external_reference',
                                                  :version, false)
                """),
                    {
                        "id": uuid.uuid5(uuid.NAMESPACE_URL, source),
                        "title": r["title"],
                        "version": r["version"],
                    },
                )
            connection.execute(
                text("""
                INSERT INTO document_chunks VALUES
                    (:id, :doc, :idx, :body, cast(:vector as vector(384)))
            """),
                [
                    {
                        "id": uuid.uuid5(uuid.NAMESPACE_URL, r["chunk_id"]),
                        "doc": uuid.uuid5(uuid.NAMESPACE_URL, r["source_id"]),
                        "idx": i,
                        "body": r["text"],
                        "vector": str(vectors[i]),
                    }
                    for i, r in enumerate(records)
                ],
            )
            with Session(bind=connection) as session:
                for query in protocol["queries"]:
                    begin = time.monotonic()
                    result = retrieve_policy_evidence(session, query["query"])
                    latency = time.monotonic() - begin
                    ids = []
                    if isinstance(result, PolicyEvidenceFound):
                        for citation in result.citations:
                            source_record = logical[str(citation.chunk_id)]
                            if (
                                hashlib.sha256(citation.chunk_text.encode()).hexdigest()
                                != source_record["sha256"]
                            ):
                                raise ValueError("Citation content mismatch")
                            ids.append(source_record["chunk_id"])
                    measured.append(
                        {
                            "id": query["id"],
                            "split": query["split"],
                            "topic_group": query["topic_group"],
                            "kind": query["kind"],
                            "expectation": query["expectation"],
                            "returned_chunks": ids,
                            "latency_seconds": latency,
                            "mechanical_citations_valid": True,
                            **query_metrics(ids, query["expected_relevant_chunks"]),
                        }
                    )
    finally:
        engine.dispose()
    aggregate = {}
    for split in ("DEV", "HELDOUT"):
        positives = [
            r
            for r in measured
            if r["split"] == split and r["expectation"] == "RETRIEVE"
        ]
        negatives = [
            r for r in measured if r["split"] == split and r["expectation"] == "ABSTAIN"
        ]
        aggregate[split] = {
            "positive_queries": len(positives),
            "negative_queries": len(negatives),
            "positive_retrieved": sum(not r["abstained"] for r in positives),
            "negative_abstained": sum(r["abstained"] for r in negatives),
            **{
                key: statistics.mean(r[key] for r in positives)
                for key in ("precision_at_5", "recall_at_5", "mrr_at_5", "ndcg_at_5")
            },
        }
    result_payload = {
        "status": "MEASURED",
        "model": MODEL_NAME,
        "revision": MODEL_REVISION,
        "gate": 0.620313,
        "rrf_k": 60,
        "top_k": 5,
        "protocol": protocol["protocol"],
        "corpus_sha256": sha256_file(corpus),
        "freeze_sha256": sha256_file(directory / "retrieval-freeze.json"),
        "embedding_seconds": embedding_seconds,
        "total_seconds": time.monotonic() - start,
        "queries": measured,
        "aggregate": aggregate,
        "label_provenance": (
            "AI-proposed; maintainer-approved; not independent expert labels"
        ),
        "uncertainty": "NOT_ESTIMABLE: only three positive topic families per split",
        "limitations": (
            "Mechanical citation validity does not prove semantic support. "
            "No generated answers, applicability beyond the reviewed labels, "
            "or overall AI accuracy claim."
        ),
    }
    with output.open("x") as stream:
        stream.write(json.dumps(result_payload, indent=2) + "\n")
    return result_payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = run(args.directory, args.corpus, args.output)
    print(json.dumps(result["aggregate"], indent=2))
