# Meridian AML investigation copilot

Meridian is a **synthetic-data prototype** for human AML investigators. It gathers
traceable evidence, computes deterministic transaction and graph signals,
retrieves policy references, screens a synthetic watchlist, and assembles reports
for authenticated human review. It does not make money-laundering determinations,
file regulatory reports, or freeze accounts.

The modular monolith uses FastAPI, SQLAlchemy Core, PostgreSQL/pgvector, Alembic,
Streamlit and a pinned local BGE embedding model. Structured financial analysis
uses deterministic SQL/Python. RAG is limited to policy documents. There is no
LLM-generated final decision or composite risk score.

## Local Docker demonstration

Requirements: Docker Compose, network access for the initial image/model download,
and sufficient disk space for the locked Linux PyTorch dependencies. The image
runs Python 3.11 as a non-root user, includes the pinned model/tokenizer, and uses
offline inference at runtime. API/UI/database ports bind to loopback only.

```bash
cp .env.example .env
# Set distinct local database passwords before first database startup.
docker compose build app
docker compose up -d --wait db
docker compose run --rm maintenance
docker compose run --rm maintenance python -m meridian.loader.main
docker compose up -d --wait app ui
curl http://127.0.0.1:8000/health
```

API documentation: http://127.0.0.1:8000/docs

Streamlit: http://127.0.0.1:8501

`maintenance` runs migrations by default. Only that service receives privileged
maintenance credentials; the API receives only the application-role URL, and the
UI receives no database credentials. The seed command loads synthetic customers,
transactions, graph data, four policy documents, ten chunks, a synthetic watchlist,
and two development users. It refuses to clear source data after alerts exist;
do not bypass that check to reseed a used database.

Issue a short-lived token in your own terminal, then enter it in the UI:

```bash
docker compose run --rm maintenance python -m meridian.identity.cli issue dev.senior.analyst.1@meridian.local --ttl 1 --label local-demo
```

The token is displayed once. Keep it private. Revoke it afterward using the
returned token ID:

```bash
docker compose run --rm maintenance python -m meridian.identity.cli revoke TOKEN_ID
```

After entering the token, the first-run form is prefilled with the seeded values:

- Customer ID: `04544721-686b-5e18-b4ad-1599f66d6cb3` (synthetic Rahul Sharma).
- Alert type: `large_transaction`.
- Transaction ID: `beafcbac-3048-5134-ae01-fd7585a5ef49` (INR 980,000 transfer).

Create Case → Investigate → Fetch Report → review evidence and screening → Submit
Decision → Fetch Audit Trail. A Transaction ID is required for transaction-based
evidence; clearing it intentionally yields an incomplete investigation. The UI
recognizes `INCOMPLETE_INSUFFICIENT_EVIDENCE` and does not claim completion.
REQUEST_MORE_INFO is restricted to the assigned analyst; the senior demo token
cannot perform that action, and there is no assignment administration UI.

The senior analyst can perform the supported approval demonstration without an assignment
workflow. Analyst assignment management remains deferred under ADR-0007.
Use `large_transaction` for the seeded worked example; `new_beneficiary` and
`rapid_movement` are also documented policy query types. Legacy `AML_*` fixture
query strings are provisional and may abstain.

For repeatable HTTP verification, install the host environment below, securely
set `MERIDIAN_DEMO_TOKEN` to the issued senior token, and run:

```bash
PYTHONPATH=src uv run --frozen --no-sync python -m meridian.evaluation.demo --output /tmp/meridian-demo.json
unset MERIDIAN_DEMO_TOKEN
```

This creates a synthetic case, investigates it, verifies report/evidence links,
checks screening, records a synthetic APPROVE action, and reconstructs its audit
trail. It also checks unauthenticated and client-supplied actor rejection. It is
restricted to localhost. It does not remove the case afterward.

Stop the demonstration with `docker compose stop`. The named database volume
retains cases and audit records. Do not remove it unless deliberately discarding
all local demo data.

## Host development and verification

```bash
uv sync --frozen --python 3.11 --group ui
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync mypy src/
```

Use Python 3.11 and the committed lock. The separate disposable test database is
`meridian_test` on loopback port 55432 with an explicit safety marker. Follow
[TESTING.md](docs/TESTING.md) to start it and export its three role URLs; then:

```bash
HF_HUB_OFFLINE=1 uv run --frozen --no-sync pytest -q tests/
uv run --frozen --no-sync pip-audit
```

Offline tests require the pinned model to be cached on the host. The container
model cache is separate. Never point test URLs at the demo database.

## Evaluations and limits

With the guarded test URLs exported and no concurrent tests:

```bash
PYTHONPATH=src HF_HUB_OFFLINE=1 uv run --frozen --no-sync python -m meridian.evaluation.run --output /tmp/meridian-evaluation.json
```

This replaces disposable source fixtures and runs existing synthetic amount,
transaction, graph, ER and sanctions baselines. It reuses the recorded policy
HELDOUT result; **do not rerun or retune that frozen split**. See
[EVALUATION.md](docs/EVALUATION.md), [ADR-0009](docs/decisions/0009-policy-absolute-relevance-gate.md)
and the versioned JSON artifacts for exact measurements and limitations.

The cosine gate is a maintainer-approved prototype, not calibrated. Retrieved
chunks do not establish policy applicability or citation correctness. ER remains
an exact-name/exact-DOB candidate primitive, not a persisted identity merge.
Watchlist matches require human review; no match is not sanctions clearance.
Human-comparison evaluation is **NOT PERFORMED**. Synthetic metrics do not measure
real-world AML performance.

Security controls include RBAC, expiring/revocable hashed tokens, atomic human
decision audits, scoped evidence references, least-privilege roles, bounded error
codes, secret exclusions from images, and fail-closed database test guards.
This remains a local prototype: production IAM, assignment administration,
retention/deletion policy, comprehensive free-text PII redaction, TLS deployment,
load testing and operational monitoring are not established. Never load real
customer data or expose these development services publicly.
