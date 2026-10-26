# Portfolio release remediation — 2026-10-26

## Result

The focused remediation is **IMPLEMENTED and TESTED**, ready for feature-branch
push review. No push or merge was performed for this remediation.

Base: `53e26dc36453f273c2d61dbee05c64dd9323059c`, merged via
[PR #40](https://github.com/001ankurmishra/meridian/pull/40).
The base tree matches the Phase B final commit. Its
[post-merge CI](https://github.com/001ankurmishra/meridian/actions/runs/40260592866)
was independently checked as completed/success. This does not imply CI has run
for the new local changes.

Branch: `feature/portfolio-release-integrity`. No historical migration was edited.

## Defects corrected

1. **Repeated investigation admission:** case status validation, non-FAILED run
   detection and INSERT now share one transaction holding a PostgreSQL case-row
   lock. Sequential and concurrent supported requests cannot create duplicate
   active/non-failed runs. Explicit retries are allowed only after FAILED runs
   while the case remains OPEN. Complete/incomplete runs cannot be rerun. No case
   state-machine changes or automatic retries were introduced.
2. **Ambiguous historical reports:** the report API and decision service reject
   multiple non-failed historical runs instead of choosing one by recency. Failed
   history is retained. Selection among failed runs has a deterministic tie-break.
3. **Unsupported final decisions:** per Ankur's explicit clarification, both
   APPROVE and REJECT require a COMPLETE run, a valid report and at least one
   evidence-backed recommendation. All decisions wait for active runs to finish.
   ESCALATE and REQUEST_MORE_INFO still permit missing/failed/incomplete
   investigations under existing RBAC and case-transition rules.
4. **Missing audit provenance:** human decisions store the selected run ID in the
   existing audit FK and snapshot its status. The audit API exposes the ID.
   Validation uses the same connection/transaction as case update and audit
   insertion; invalid evidence or audit failure leaves the case unchanged.
5. **Demo guidance:** the Streamlit form defaults to `large_transaction` and real
   seeded customer/transaction UUIDs. Missing transaction evidence is explained;
   `INCOMPLETE_INSUFFICIENT_EVIDENCE` is recognized explicitly. REQUEST_MORE_INFO's
   assigned-analyst restriction and final-decision prerequisites are visible.
6. **Overbroad source grants:** forward migration `c832e05a1201` revokes app
   INSERT/UPDATE on entities and graph_relationships, and UPDATE on alerts.
   Alert INSERT and required case/investigation/evidence/audit writes remain.

## Actual tests and quality gates

Environment: Python 3.11.13, committed uv lock, frozen/no-sync invocation,
`UV_PYTHON=3.11`, `UV_NO_SYNC=1`, `HF_HUB_OFFLINE=1`. PostgreSQL test target:
`meridian_test`, loopback port 55432, disposable marker `on`, READ COMMITTED.
No production/demo database was used for destructive tests.

| Command/check | Result |
|---|---|
| `uv run --frozen --no-sync ruff check .` | PASS |
| `uv run --frozen --no-sync mypy src/` | PASS, 96 source files |
| `uv run --frozen --no-sync pytest -q tests/` | **874 passed, 4 warnings, 43.91s** |
| Run-admission/evidence/orchestrator targeted set | 36 passed |
| Grants/UI/worked-example targeted set | 28 passed |
| Human action/state/role, audit and identity targeted set | 161 passed |
| Corrected audit-history/live UI targeted set | 15 passed |
| `git diff --check` | PASS |

The full suite includes sequential duplicate rejection, two simultaneous HTTP
requests through the ASGI application with real PostgreSQL admission, FAILED
retry, ambiguous historical reports, all four actions across five run states and
five actor categories, corrupt COMPLETE reports, audit rollback, and a concurrent
human-decision/investigation-start test. Live FastAPI + Streamlit AppTest verifies
that the seeded transaction path can be approved, while a transaction-free
incomplete case cannot be approved but can be escalated. Assertions were retained
or strengthened; no skips or safety-check suppression were introduced.

Warnings concern Starlette's httpx TestClient integration and deprecated naming
of the HTTP 422 constant. They are not test failures.

Intermediate failures were resolved: a privilege test left an alert that correctly
blocked the loader, so its own rows are now cleaned up; a stopped test database
caused setup errors and was restarted; two legacy tests expected duplicate
non-failed runs or approval of incomplete cases, and now exercise FAILED retry
and the documented supported demo/triage paths. The UI test submits form edits
with the button in one AppTest run rather than forcing a separate unsubmitted
form rerun. The final full-suite result above supersedes those intermediate runs.

## Migration, permissions and historical data

The guarded pytest migration fixture successfully applied the forward migration,
then downgraded to base and rebuilt through all 13 revisions. A subsequent direct
read confirmed head `c832e05a1201`. Existing local demo history was inspected:
two runs across two cases, zero duplicate non-failed case histories; the original
schema has only the investigation-run primary-key index. No uniqueness constraint
or historical data rewrite was introduced, so existing rows remain compatible.

Effective permissions across every public table were captured before and after:

- `portfolio-grants-before.json`
- `portfolio-grants-after.json`
- `portfolio-runtime-role.json`

The difference is exactly five revoked grants. Effective column privileges were
also checked. The application role is not superuser and has no CREATE ROLE,
CREATE DATABASE, replication, bypass-RLS or inherited memberships. It has public
schema USAGE but not CREATE. Database CONNECT and existing TEMP permission remain.
Runtime graph writes and alert UPDATE are denied by actual statements, not merely
by inspection of migration source. Loader/seed and end-to-end workflow tests pass.

## Local implementation commits

- `3aa6799` — atomic investigation admission and ambiguous-report rejection.
- `3cf735d` — forward migration and effective runtime-grant verification.
- `7f01965` — seeded demo defaults and incomplete-state guidance.
- `e148930` — COMPLETE-only final decisions, atomic report validation and run-linked audit.

Final documentation/evidence is committed separately; the handoff identifies
final HEAD. The complete changed-file inventory is `portfolio-release-files.txt`.

## Security implications and remaining limits

The changes reduce duplicate execution, unsupported final decisions, ambiguous
audit reconstruction and unnecessary database writes. Existing token secrecy,
RBAC, sanctions semantics, evidence validation and disposable-database guard remain.
No new service, model, agent, scoring system, external IAM or assignment mechanism
was added. Review of scoped changes found no credential material or unrelated files.

Run admission is a transactionally atomic service boundary, not a new uniqueness
constraint: ad hoc privileged SQL can bypass it. Legacy ambiguity requires explicit
maintainer review; records are not automatically repaired or deleted. No retry or
reopening workflow for completed/incomplete cases was invented. Evidence validation
proves source/link integrity under existing contracts, not semantic accuracy of
AML interpretations. This remains a synthetic prototype, not production-ready.

Frozen RAG HELDOUT results were neither rerun nor retuned; the evaluation artifact
folder has no changes from the merge base. Human comparison remains NOT PERFORMED.
Dependencies were unchanged; no new vulnerability-scan claim is made. This pass
verified the host/live-API/Streamlit test path and fresh test migrations; it did
not rebuild or redeploy the Docker image. Existing demo containers may still run
older code until rebuilt using the README instructions. New-branch remote CI is
NOT RUN because the changes have not been pushed.
