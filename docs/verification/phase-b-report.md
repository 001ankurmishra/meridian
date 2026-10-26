# Phase B verification report — 2026-10-26 (Asia/Kolkata)

## Outcome

**VERIFIED:** The scoped local synthetic prototype executes intake → investigation
→ evidence-backed report → authorized synthetic human-decision action → audit
reconstruction, including authoritative synthetic watchlist screening. This is
not a production-readiness claim or completion of every roadmap feature.

Baseline: `95e656dddd7cab9f251435bc1a0d1a48a0184f27`.
Branch: `feature/phase-b-verifiable-prototype`. Baseline ancestry was preserved;
no reset, history rewrite, push or merge was performed. Final HEAD is reported
in the maintainer handoff after the final local commit.

## Implementation and evidence

| Area | Status and evidence |
|---|---|
| Execution | Python 3.11, frozen lock, subprocesses use the active interpreter; disposable test database guard retained |
| Evidence safety | Source resolution, same-investigation producer/evidence/finding checks, report completeness revalidation; negative tests in `test_evidence_integrity.py` |
| Failure safety | Graph technical failure fails the investigation; controlled abstention and ADR-0008 sanctions semantics retained; bounded persisted/audit error codes |
| Authentication | Privileged maintenance-only provisioning, token lifecycle audit, expiry/revocation/deactivation, role checks and actor-field rejection; transactional decision audit tested |
| Policy retrieval | Maintainer-approved label/freeze record and ADR-0009; pinned model/tokenizer; unchanged RRF ranking; one locked paired HELDOUT measurement |
| Streamlit | Seven authoritative screening states, incomplete/failed messaging, uncertainty, bounded HTTP requests and authenticated review tested |
| Security | Eight original advisories individually reviewed; subsequent scan included 37 additional Pillow findings; targeted compatible fixes, no mass upgrade |
| Evaluation | Unified guarded baseline runner executed; immutable policy result reused; human comparison NOT PERFORMED |
| Deployment | Actual Linux/arm64 image build, fresh database migrations, seed, API/UI health and synthetic HTTP workflow demonstrated |

Verified local commits before deployment finalization:

- `165c3ce`: Python/test environment and Docker secret exclusions.
- `19bd073`: evidence and failure safety.
- `55ad77a`: maintenance credentials, identity lifecycle and database permissions.
- `9871580`: approved protocol freeze, pinned model and evaluation harness.
- `8695072`: Streamlit screening and bounded requests.
- `a9e70ad`: reviewed dependency fixes.
- `8f6f911`: accepted prototype gate and locked paired plan.
- `1175b29`: unified evaluation and measured policy artifacts.

The complete changed-file inventory is `phase-b-changed-files.txt` in this folder.
Final review found no unrelated changes or credential material in the changed
files or local implementation commit diffs. Public demonstration placeholders
in `.env.example` remain explicitly labeled; real verification credentials stay
outside the repository.

## Tests actually executed

Commands used the guarded test database, `HF_HUB_OFFLINE=1`, `UV_PYTHON=3.11`,
`UV_NO_SYNC=1`, and `uv run --frozen --no-sync`:

| Check | Observed result |
|---|---|
| `ruff check .` | PASS |
| `mypy src/` | PASS, 96 source files |
| `pytest -q tests/` | 752 passed, 3 warnings, 42.36 seconds |
| Targeted fixture/retrieval/unified runner tests after correction | 23 passed |
| Host dependency scan after controlled upgrades | Zero known vulnerabilities |
| Installed Linux image Python dependency scan | 97 distributions; zero known vulnerabilities; `../security/image-advisories.json` |
| Fresh migrations | All 12 revisions through `b714c29f1001` on a new named volume |
| Runtime permissions and evidence references | PASS; `phase-b-runtime.json` |
| Containerized HTTP demo | PASS; `phase-b-demo.json` |
| Streamlit | Container health endpoint returned `ok`; browser rendered authentication page; authenticated AppTest/live API smoke covered by full suite |

The three warnings concern Starlette's deprecated httpx TestClient integration
and old HTTP 422 constant naming. No test was skipped or assertion disabled.

Intermediate failures were investigated: the ER adapter initially supplied only
its manifest instead of its required full fixture; this was corrected. Two full
suite failures used an unaligned fake embedding and provisional legacy query
strings; the tests now use a real pinned embedding and supported C1 alert input,
while preserving their success/evidence assertions. The first deployment verifier
incorrectly excluded the report's separate policy-evidence section when checking
finding links; the verifier now checks the union. That first synthetic case remains
open for traceability; the successful second case is closed approved. A diagnostic
read of `alembic_version` was denied to the app role; verification used maintenance
access instead, without broadening grants.

## Deployment details

Isolated Compose project: `meridian-verify`. Existing test database was not reused
for deployment. New volume: `meridian-verify_meridian_data`.

- API: `http://127.0.0.1:8410`
- Streamlit: `http://127.0.0.1:8510`
- Demo database: loopback port 55433; tests remain on 55432.
- Private verification environment: `/tmp/meridian-verify.env`, mode 0600;
  credentials are not in this repository or report.
- Image runs as UID 10001; API database role is `meridian_app`.
- Final refreshed image: `sha256:3b1896043222da45f4f5a739bd492c9202f057488e6a145faf3bc385ec30f817`,
  Linux/arm64, 3,619,542,163 bytes. All 96 container Python source files match
  the workspace byte-for-byte; `phase-b-image.json` retains their hashes.
  API, UI and database healthchecks passed after the refresh.
- No DATABASE_URL, MAINTENANCE_DATABASE_URL or LOADER_DATABASE_URL in API runtime.
- Identity tables are read-only to the app; audit/evidence/screening mutation
  grants remain append-only. All 28 evidence pointers across two demo runs resolve.
- Seed: 104 customers, 509 transactions, four policy documents, ten chunks,
  ten watchlist entries. Every source is synthetic.
- Successful case: five findings, thirteen evidence references including five
  policy references, four recommendations, `NO_CANDIDATE_MATCH` against watchlist v1,
  `CLOSED_APPROVED` and exactly one authorized approval audit event.
- Both temporary verification tokens were revoked; none remain active.

Reproduction commands and token handling are in the root README. The seed loader
refuses to clear source records after alerts exist. Containers remain available
for local review; stopping them preserves the named database volume.

## Evaluation interpretation

The fixed gate rejected all five assessed HELDOUT negatives previously retrieved
by the RRF baseline, retained all eight assessed HELDOUT positives and all three
C1 descriptive queries. Four HELDOUT queries were NOT_ASSESSED; C2 was excluded.
C4 strict Hit@1=0.875, MRR=0.9375, precision@5=0.525, recall@5=0.958333; ranking is
unchanged between systems. No HELDOUT threshold selection or second run occurred.
Labels are maintainer-approved, not independently validated; the nine-example
DEV selection is not calibration, policy applicability or citation correctness.

The unified artifact reports weaknesses as measured: v0.2 amount eval AUC 0.479167;
v0.3 amount/beneficiary-age/velocity eval AUCs 0.703125/0.521368/0.484375. Graph
cycle and chain-depth structural checks matched all 58 fixture oracles. ER found
7 of 15 ground-truth pairs with 1 false positive; seven in-scope pairs were found.
Sanctions matched its designed candidate outputs, including a false positive and
a missed ground-truth positive. These are synthetic fixture measurements only.

## Remaining limitations and handoff

- Human comparison: NOT PERFORMED. No real-world AML effectiveness claim.
- C2 legacy workflow, independent relevance labels and citation correctness remain
  unverified. Any future threshold needs a new evaluation protocol.
- Analyst assignment administration, external IAM, comprehensive free-text PII
  redaction and a maintainer-defined retention/deletion policy remain deferred.
- Adverse media, richer graph analytics, ER persistence/merging, composite risk
  calibration, React migration and OpenTelemetry were not added.
- OS/base-image vulnerability scanning, load/resilience testing and production
  deployment are NOT PERFORMED. Linux image size is large because the existing
  PyPI torch lock includes CUDA packages despite CPU inference.
- GitHub CI for this feature branch is NOT RUN because the branch is not pushed.
  CI configuration now pins uv, uses frozen/no-sync commands, and blocks on
  dependency vulnerabilities. Remote main was `a4cb902af09ec7974df0ed0392ee1f625c6cb51b`;
  connector status/PR-run lookups returned no entries, not proof of a passing run.
- Official origin is `https://github.com/001ankurmishra/meridian.git`. A local Git
  credential authenticated successfully to GitHub's repository API and reports
  push permission; the connected GitHub account also has access. No token value
  was exposed or stored in artifacts. See `phase-b-remote.json`.

A recruiter/engineer can truthfully inspect the local synthetic investigation,
its evidence references, screening outcome, authorized review and audit trail,
and reproduce the recorded baseline evaluation. Production readiness, calibrated
AML accuracy and independent human validation cannot be claimed.

**Next external action requires Ankur's explicit approval:** push this verified
feature branch to origin. Do not merge into main automatically.


## Merge and portfolio-remediation addendum — 2026-10-26

Phase B was subsequently published and merged through
[PR #40](https://github.com/001ankurmishra/meridian/pull/40).
The verified merged main commit is
`53e26dc36453f273c2d61dbee05c64dd9323059c`; its tree matches the Phase B final
commit. [Post-merge push CI #40260592866](https://github.com/001ankurmishra/meridian/actions/runs/40260592866)
reported `completed/success`, independently checked through GitHub's API.
The earlier no-push/no-merge/CI-not-run statements above describe the original
handoff, not the current repository state.

A subsequent focused audit identified real omissions despite the original 752
passing tests: repeated investigation admission, missing human-decision run
prerequisites/provenance, stale demo defaults and unnecessary runtime source-write
grants. These are being corrected on `feature/portfolio-release-integrity`, based
on the verified merge. The original Phase B report is retained as historical
evidence, not used to claim those omissions were already fixed. See
`portfolio-release-report.md` for final remediation verification.
