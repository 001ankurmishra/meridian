"""Read-only retrieval evaluation with freeze and corpus identity gates."""

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from meridian.agents.policy.model_config import MODEL_NAME, MODEL_REVISION
from meridian.evaluation.policy_metrics import aggregate, score_ranking
from meridian.fixtures.policy_retrieval_eval_set import (
    ChunkRef,
    build_eval_set,
    canonical_sha256,
)

EVALUATION_DIR = Path(__file__).resolve().parents[3] / "docs" / "evaluation"


def validate_freeze() -> str:
    fixture = build_eval_set()
    record = json.loads(
        (EVALUATION_DIR / "policy_retrieval_eval_v1.freeze.json").read_text()
    )
    digest = canonical_sha256(fixture)
    if (
        record["status"] != "FROZEN"
        or fixture.protocol_status != "FROZEN"
        or digest != record["frozen_sha256"]
        or not record["approved_by"]
    ):
        raise ValueError("Evaluation requires the approved frozen payload.")
    if (fixture.model_name, fixture.model_snapshot) != (MODEL_NAME, MODEL_REVISION):
        raise ValueError("Model revision mismatch; results would not be comparable.")
    return digest


def measure(engine: Engine, phase: str) -> dict[str, Any]:
    if phase not in {"DEV", "HELDOUT", "DESCRIPTIVE"}:
        raise ValueError("Unknown evaluation phase.")
    digest = validate_freeze()
    if phase == "HELDOUT":
        plan = json.loads(
            (EVALUATION_DIR / "policy_retrieval_eval_v1.plan.json").read_text()
        )
        if (
            plan["status"] != "LOCKED"
            or plan["frozen_sha256"] != digest
            or plan["rrf_threshold"] != 0.01
            or plan["absolute_gate"] != "DISABLED"
        ):
            raise ValueError("HELDOUT requires the locked baseline evaluation plan.")
    # Lazy imports: validating the freeze/metrics needs no model download or DB access.
    from meridian.agents.policy.policy_agent import (
        PolicyEvidenceFound,
        retrieve_policy_evidence,
    )
    from meridian.agents.policy.retrieval import embed_query, retrieve_candidates

    fixture = build_eval_set()
    refs = list(fixture.chunk_refs)
    rows: list[dict[str, Any]] = []
    with Session(engine) as session:
        corpus = session.execute(
            text(
                "SELECT d.title, d.version, c.chunk_index, c.chunk_text, c.embedding "
                "FROM document_chunks c JOIN documents d USING (document_id)"
            )
        ).all()
        actual = [
            ChunkRef(
                row.title,
                row.version,
                row.chunk_index,
                hashlib.sha256(row.chunk_text.encode()).hexdigest(),
            )
            for row in corpus
        ]
        if len(actual) != len(refs) or set(actual) != set(refs):
            raise ValueError("Database corpus differs from frozen chunk identities.")
        if any(row.embedding is None for row in corpus):
            raise ValueError("Corpus contains missing embeddings.")
        for query in fixture.queries:
            if (phase == "DESCRIPTIVE" and query.cohort != "C1") or (
                phase != "DESCRIPTIVE" and query.split != phase
            ):
                continue
            candidates = retrieve_candidates(
                session, query.query_text, k=fixture.retrieval_k, top_k=len(refs)
            )
            ranking = [
                refs.index(
                    ChunkRef(
                        c["title"],
                        c["version"],
                        c["chunk_index"],
                        hashlib.sha256(c["chunk_text"].encode()).hexdigest(),
                    )
                )
                for c in candidates
            ]
            decision = retrieve_policy_evidence(
                session, query.query_text, k=60, top_k=5, confidence_threshold=0.01
            )
            row: dict[str, Any] = {
                "query_id": query.query_id,
                "cohort": query.cohort,
                "split": query.split,
                "ranking": ranking,
                "metrics": score_ranking([j.grade for j in query.judgments], ranking),
                "expected_abstention": query.abstention_ground_truth.value,
                "system_decision": "RETRIEVE"
                if isinstance(decision, PolicyEvidenceFound)
                else "ABSTAIN",
            }
            if phase == "DEV":
                # Exploration only; never changes ranking or production decisions.
                vector = str(embed_query(query.query_text))
                similarity = session.scalar(
                    text(
                        "SELECT max(1 - (embedding <=> cast(:vector as vector(384)))) "
                        "FROM document_chunks"
                    ),
                    {"vector": vector},
                )
                row["exploratory_max_cosine_similarity"] = float(similarity)
            rows.append(row)
    return {
        "protocol": fixture.version,
        "frozen_sha256": digest,
        "phase": phase,
        "model_revision": MODEL_REVISION,
        "device": "cpu",
        "tier": "PROTOTYPE",
        "rrf_threshold": 0.01,
        "absolute_gate": "DISABLED",
        "human_comparison": "NOT PERFORMED",
        "labels_independently_validated": False,
        "limitations": "Small synthetic corpus; no calibration or real-world claim. "
        "C2 excluded pending confirmation of supported legacy workflow.",
        "cohorts": aggregate(rows),
        "queries": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=["DEV", "HELDOUT", "DESCRIPTIVE"], required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite evaluation evidence.")
    # Fail closed before loading the model or opening a connection.
    validate_freeze()
    engine = create_engine(os.environ["APP_DATABASE_URL"], hide_parameters=True)
    try:
        report = measure(engine, args.phase)
        with args.output.open("x") as output:
            json.dump(report, output, indent=2, sort_keys=True)
            output.write("\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
