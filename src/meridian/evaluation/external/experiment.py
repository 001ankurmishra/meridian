"""Isolated CPU DEV experiments; immutable scores, pinned safe weights, TEMP SQL."""

import argparse
import importlib.metadata
import json
import os
import platform
import resource
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from meridian.evaluation.external.ibm import sha256_file
from meridian.evaluation.external.selection import canonical_hash, load_dev_protocol
from meridian.testing.guard import verify_test_database_safety


def snapshot(spec: dict[str, Any]) -> Path:
    """Download only pinned non-executable configs/tokenizers and safe weights."""
    from huggingface_hub import snapshot_download

    path = Path(
        snapshot_download(
            spec["model"],
            revision=spec["revision"],
            token=False,
            allow_patterns=["*.json", "*.txt", "*.model", "model.safetensors"],
            max_workers=2,
        )
    )
    expected = spec["weights"][0]
    weights = path / "model.safetensors"
    if (
        weights.stat().st_size != expected["size"]
        or sha256_file(weights) != expected["lfs"]["sha256"]
    ):
        raise ValueError("Model weight integrity mismatch")
    return path


def rss_bytes() -> int:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(rss if platform.system() == "Darwin" else rss * 1024)


def setup_tables(
    conn: Connection,
    rows: list[dict[str, Any]],
    vectors: list[list[float]],
    dim: int,
) -> None:
    if dim not in (384, 768) or len(rows) != len(vectors):
        raise ValueError("Unsupported shape")
    if any(len(v) != dim for v in vectors):
        raise ValueError("Embedding dimension mismatch")
    conn.execute(
        text(f"""CREATE TEMP TABLE v3_chunks (
        chunk_id uuid, logical_id text, title text, version text,
        chunk_index integer, body text, embedding vector({dim})
    ) ON COMMIT DROP""")
    )
    conn.execute(
        text(f"""INSERT INTO v3_chunks VALUES
        (:id, :logical, :title, :version, :idx, :body, cast(:v as vector({dim})))"""),
        [
            dict(
                id=uuid.uuid5(uuid.NAMESPACE_URL, r["chunk_id"]),
                logical=r["chunk_id"],
                title=r["title"],
                version=r["version"],
                idx=i,
                body=r["text"],
                v=str(vectors[i]),
            )
            for i, r in enumerate(rows)
        ],
    )


def hybrid(
    conn: Connection,
    query: str,
    vector: list[float],
    dim: int,
) -> dict[str, Any]:
    if dim not in (384, 768) or len(vector) != dim:
        raise ValueError("Unsupported query shape")
    ordering = 'title COLLATE "C", version COLLATE "C", chunk_index, chunk_id'
    lexical = (
        conn.execute(
            text(f"""SELECT logical_id FROM v3_chunks
        WHERE to_tsvector('english', body) @@ plainto_tsquery('english', :q)
        ORDER BY ts_rank_cd(to_tsvector('english', body),
                    plainto_tsquery('english', :q)) DESC, {ordering}"""),
            {"q": query},
        )
        .scalars()
        .all()
    )
    semantic = (
        conn.execute(
            text(f"""SELECT logical_id,
        1-(embedding <=> cast(:v as vector({dim}))) AS cosine,
        title, version, chunk_index, chunk_id FROM v3_chunks
        ORDER BY embedding <=> cast(:v as vector({dim})), {ordering}"""),
            {"v": str(vector)},
        )
        .mappings()
        .all()
    )
    lr = {cid: i for i, cid in enumerate(lexical, 1)}
    fused = [
        dict(
            chunk_id=r["logical_id"],
            cosine=float(r["cosine"]),
            rrf=1 / (60 + i)
            + (1 / (60 + lr[r["logical_id"]]) if r["logical_id"] in lr else 0),
            tie=(r["title"], r["version"], r["chunk_index"], str(r["chunk_id"])),
        )
        for i, r in enumerate(semantic, 1)
    ]
    fused.sort(key=lambda r: (-r["rrf"], r["tie"]))
    return dict(
        max_cosine=max((r["cosine"] for r in fused), default=None),
        candidates=[{k: v for k, v in r.items() if k != "tie"} for r in fused[:50]],
    )


def run(
    directory: Path,
    corpus: Path,
    output: Path,
    model_index: int,
    first_stage: Path | None = None,
) -> dict[str, Any]:
    protocol = load_dev_protocol(directory / "dev-proposals.json", corpus)
    manifest = json.loads((directory / "models.json").read_text())
    spec = manifest["models"][model_index]
    if output.exists() or output.with_suffix(".started.json").exists():
        raise FileExistsError("Existing run: inspect evidence before resuming")
    if (spec["kind"] == "cross_encoder") != (first_stage is not None):
        raise ValueError("Reranker requires an embedding result")
    rows = [json.loads(line) for line in corpus.read_text().splitlines()]
    queries = protocol["queries"]
    upstream = json.loads(first_stage.read_text()) if first_stage else None
    if upstream and (
        upstream["protocol_sha256"] != canonical_hash(protocol)
        or upstream["corpus_sha256"] != sha256_file(corpus)
        or [q["id"] for q in upstream["queries"]] != [q["id"] for q in queries]
        or upstream["kind"] != "embedding"
    ):
        raise ValueError("First-stage provenance mismatch")
    verify_test_database_safety()
    output.parent.mkdir(parents=True, exist_ok=True)
    config = dict(
        model=spec,
        corpus_sha256=sha256_file(corpus),
        protocol_sha256=canonical_hash(protocol),
        cpu_threads=4,
        first_stage_sha256=sha256_file(first_stage) if first_stage else None,
        code_sha256=sha256_file(Path(__file__)),
        batch_size=16,
        candidate_depth=50,
        rrf_k=60,
    )
    with output.with_suffix(".started.json").open("x") as f:
        json.dump(config, f, indent=2)
    start = time.monotonic()
    model_path = snapshot(spec)
    download_seconds = time.monotonic() - start
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    torch.set_num_threads(4)
    torch.set_num_interop_threads(1)
    torch.manual_seed(20261027)
    torch.use_deterministic_algorithms(True)
    start = time.monotonic()
    model: Any
    if spec["kind"] == "embedding":
        model = SentenceTransformer(
            str(model_path),
            device="cpu",
            trust_remote_code=False,
            local_files_only=True,
            model_kwargs={"use_safetensors": True},
        )
        if model.get_sentence_embedding_dimension() != spec["dimensions"]:
            raise ValueError("Actual dimension mismatch")
    else:
        model = CrossEncoder(
            str(model_path),
            device="cpu",
            max_length=512,
            trust_remote_code=False,
            local_files_only=True,
            model_kwargs={"use_safetensors": True},
            activation_fn=torch.nn.Identity(),
        )
    model.float()
    load_seconds = time.monotonic() - start
    measured = []
    truncations = 0
    document_seconds = 0.0
    vectors: list[list[float]] = []
    if spec["kind"] == "embedding":
        texts = [r["text"] for r in rows]
        lengths = model.tokenizer(texts, truncation=False)["input_ids"]
        truncations += sum(len(v) > model.max_seq_length for v in lengths)
        start = time.monotonic()
        vectors = model.encode(
            texts, normalize_embeddings=True, batch_size=16, show_progress_bar=False
        ).tolist()
        document_seconds = time.monotonic() - start
        # Weight/corpus/protocol/config-keyed immutable cache; no pickle.
        cache = output.with_suffix(".vectors.json")
        with cache.open("x") as f:
            json.dump(dict(config_sha256=canonical_hash(config), vectors=vectors), f)
        engine = create_engine(os.environ["APP_DATABASE_URL"], hide_parameters=True)
        try:
            with engine.begin() as conn:
                setup_tables(conn, rows, vectors, spec["dimensions"])
                # Warm-up is explicitly excluded from query timings.
                model.encode(
                    spec["query_prefix"] + queries[0]["query"],
                    normalize_embeddings=True,
                )
                for q in queries:
                    full = spec["query_prefix"] + q["query"]
                    truncations += int(
                        len(model.tokenizer(full)["input_ids"]) > model.max_seq_length
                    )
                    start = time.monotonic()
                    v = model.encode(full, normalize_embeddings=True).tolist()
                    encoded = time.monotonic()
                    result = hybrid(conn, q["query"], v, spec["dimensions"])
                    measured.append(
                        dict(
                            id=q["id"],
                            **result,
                            query_encode_seconds=encoded - start,
                            retrieval_seconds=time.monotonic() - encoded,
                        )
                    )
        finally:
            engine.dispose()
    else:
        assert upstream is not None
        lookup = {r["chunk_id"]: r["text"] for r in rows}
        model.predict(
            [(queries[0]["query"], rows[0]["text"])],
            batch_size=1,
            show_progress_bar=False,
        )
        for q, prior in zip(queries, upstream["queries"], strict=True):
            ids = [r["chunk_id"] for r in prior["candidates"]]
            pairs = [(q["query"], lookup[cid]) for cid in ids]
            lengths = model.tokenizer(
                [p[0] for p in pairs], [p[1] for p in pairs], truncation=False
            )["input_ids"]
            truncations += sum(len(v) > 512 for v in lengths)
            start = time.monotonic()
            scores = model.predict(
                pairs, batch_size=16, show_progress_bar=False
            ).tolist()
            measured.append(
                dict(
                    id=q["id"],
                    candidates=prior["candidates"],
                    reranker_scores=dict(zip(ids, scores, strict=True)),
                    rerank_seconds=time.monotonic() - start,
                )
            )
    result = dict(
        status="MEASURED_DEV_ONLY",
        kind=spec["kind"],
        **config,
        config_sha256=canonical_hash(config),
        queries=measured,
        download_and_integrity_seconds=download_seconds,
        cold_model_load_seconds=load_seconds,
        document_encode_seconds=document_seconds,
        peak_process_rss_bytes=rss_bytes(),
        truncation_count=truncations,
        platform=platform.platform(),
        machine=platform.machine(),
        python=platform.python_version(),
        libraries={
            p: importlib.metadata.version(p)
            for p in [
                "torch",
                "transformers",
                "sentence-transformers",
                "sqlalchemy",
                "pgvector",
            ]
        },
    )
    with output.open("x") as f:
        json.dump(result, f, indent=2)
    print(
        json.dumps(
            {
                k: result[k]
                for k in [
                    "status",
                    "kind",
                    "cold_model_load_seconds",
                    "peak_process_rss_bytes",
                    "truncation_count",
                ]
            }
        )
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model-index", type=int, choices=[0, 1, 2], required=True)
    parser.add_argument("--first-stage", type=Path)
    args = parser.parse_args()
    run(args.directory, args.corpus, args.output, args.model_index, args.first_stage)
