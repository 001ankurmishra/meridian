# ADR 0004: Embedding Model Selection (F5 Slice 1)

Status: Proposed

## Context
Project Meridian requires semantic search over internal policies (F5 Slice 1). The system must securely embed policy chunks without relying on external APIs that might leak sensitive context or fail during outages.

## Decision
We selected **BAAI/bge-small-en-v1.5** via `sentence-transformers` for local inference.

## Rationale
- **Size and Speed**: It runs efficiently on CPU during development and easily fits within standard container memory limits.
- **Dimensionality**: Outputs 384-dimensional vectors, balancing semantic capture with pgvector storage constraints and query latency.
- **Quality**: Ranks highly on the MTEB leaderboard for its size class.
- **Cost/Privacy**: Local execution incurs $0 API cost and prevents data egress.
- **Format**: It requires an explicit prefix instruction for queries (`Represent this sentence for searching relevant passages: `) but none for documents, aligning perfectly with our chunking and retrieval logic.

## Consequences
- Requires `sentence-transformers` runtime dependency.
- First execution downloads the model weights locally, which must be cached.
- pgvector columns must be sized to `vector(384)`.
