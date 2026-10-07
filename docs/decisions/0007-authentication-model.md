# ADR-0007: Authentication, Authorization, and Case Visibility Model

Status: Proposed
Date: 2026-10-06

## Context

Meridian currently implements role-based authorization for human decisions at the library level (`record_human_decision`) but lacks API-level authentication, identity derivation, and case visibility enforcement. Endpoint callers currently assert their identity (e.g., via `DecisionRequest.actor_user_id`) without proof. A concrete authentication mechanism and access-control lifecycle must be established (Task 20) to enforce the trust boundary defined in `SECURITY.md`.

## Decision

We will implement an opaque bearer token mechanism with server-side hash storage as the smallest defensible authentication mechanism for Meridian's current portfolio/demo scope. This is not production IAM, but satisfies demo and development invariants.

### D1: Authentication Mechanism

**Chosen Mechanism:** Opaque bearer tokens with server-side SHA-256 hash storage.

**Why:** It is the smallest defensible mechanism, requires no external dependencies (unlike OIDC/IdP), avoids the complexity of session states (unlike passwords+sessions), and avoids JWT revocation complexity while maintaining strong security guarantees for the demo scope. Task 20 should verify whether existing FastAPI security helpers and the Python standard library are sufficient; no new authentication dependencies should be introduced merely for this task.

**Token Lifecycle:**
- **Generation:** 256-bit cryptographically secure random token. Never derived from user IDs, UUIDs, timestamps, or usernames.
- **Storage:** Plaintext tokens are NOT persisted. Only a cryptographic hash (SHA-256) is persisted.
- **SHA-256 Rationale:** SHA-256 is acceptable here because the bearer token has high entropy. This is NOT password hashing. Do not generalize this design to passwords.
- **Expiry:** Every credential MUST have a finite `expires_at`. No non-expiring tokens. The exact TTL is an implementation parameter for Task 20 (must be chosen, documented, and tested explicitly).
- **Revocation:** Credentials have a revocation mechanism that takes effect immediately. User deactivation must invalidate that user's credentials. No self-service revoke endpoint is required for Task 20.
- **Rotation:** No refresh-token mechanism in v1. Rotation means issuing a new credential and revoking the old one.
- **Role:** The role MUST NOT be trusted from the token. It is resolved from the current `users.role` on each authenticated request. Role changes therefore apply immediately.
- **Transport:** Bearer credentials only through the `Authorization` header. Never via URLs/query parameters. TLS is required outside localhost. (Limitation: Meridian does not currently provide production TLS infrastructure).
- **Logging:** Never log `Authorization` headers or token values. Authentication failures may be structured-log events without token material. Credential issuance/revocation must be auditable when Task 20 implements it.

**Other Evaluated Alternatives:**
- Password login + session token (rejected: too complex for demo scope)
- Stateless signed JWT (rejected: complex revocation)
- External OIDC/IdP (rejected: too heavy for standalone demo)

### D2: Server-Derived Actor

The authenticated actor MUST be derived server-side from the verified credential. The client MUST NOT be able to select the acting user.

- The current `DecisionRequest.actor_user_id` will be removed in Task 20.
- A client-supplied `actor_user_id` should be rejected rather than silently ignored.
- The authenticated identity comes from the verified token, the actor comes from that identity, and audit events record that authenticated actor.
- `record_human_decision` remains a library-level authorization function (defense-in-depth), while authentication is an API boundary concern.

### D3: HTTP Error Semantics

- **401 Unauthorized:** Missing credentials, malformed credentials, unknown credentials, expired credentials, revoked credentials, or credential referencing a nonexistent user.
- **403 Forbidden:** Authenticated user is not authorized for the requested action.
- **404 Not Found:** Authenticated user cannot see the requested case (do not disclose existence/state of inaccessible cases).
- **422 Unprocessable Entity:** Request validation errors, invalid state transitions, or other genuine semantic validation failures.

*Note:* The current unauthorized-decision API mapping of 422 must become 403 during Task 20.

**Order of Evaluation:** Authentication → Case Visibility → State Validation → Action Authorization. (Visibility must occur before state/action checks so inaccessible case state is not disclosed).

### D4: Endpoint Authorization

Authentication is required on protected case routes: `POST /cases`, `POST /cases/{id}/investigate`, `GET /cases/{id}/report`, `POST /cases/{id}/decision`, and `GET /cases/{id}/audit-trail`.

Current decision rules to preserve:
- **Approve / Reject / Escalate** on `OPEN`, `IN_REVIEW`, or `CLOSED_MORE_INFO`: assigned `analyst` or `senior_analyst`.
- **Request More Info**: assigned `analyst` only.
- **ESCALATED**: Approve / Reject by `senior_analyst` or `compliance_manager`.
- **admin**: never authorizes decisions.
- Reasons are required for Reject and Request More Info.

**Case Creation / Investigation:**
The product direction treats alert intake as system-originated, but the current four-role users table does not contain a service identity. We will not invent a fifth role for this.
*OPEN UNCERTAINTY:* The exact authentication policy for system-originated actions (like case creation/investigation via API) is deferred to future work. For now, the smallest defensible authenticated-human policy will be used without adding a new service identity.

### D5: Case Visibility

The intended visibility policy (to be implemented in Task 20) is:
- **analyst**: assigned cases only
- **senior_analyst**: all cases
- **compliance_manager**: all cases
- **admin**: all cases read-only

HTTP 404 will be used for an authenticated caller requesting a case they cannot see.

*Current State Fact:* No current production code assigns `cases.assigned_analyst_id`. Therefore, ordinary analysts currently have no API-created assigned cases until an assignment mechanism exists. Task 20 will implement authentication and visibility together, but do NOT invent or add an assignment mechanism.

### D6: Compliance Manager Policy

There is an existing inconsistency: `SECURITY.md` describes broad Approve/Reject capabilities, while `DESIGN.md` and current code (`review/decisions.py`) restrict `compliance_manager` adjudication to `ESCALATED` cases.

*Decision:* Follow the `DESIGN.md`/code behavior. `compliance_manager` may Approve/Reject `ESCALATED` cases only. Document reconciliation will be a Task 20/documentation follow-up.

### D7: Development / Demo Provisioning

Security invariants for development:
- No credential values committed to git.
- No universal/default/shared token.
- No access when no valid token is supplied.
- Tokens are never derived from deterministic dev UUIDs.
- Plaintext token appears only at controlled issuance, never logged.
- Only token hash persists.
- Issuance requires an explicit target user and finite expiry.
- The authentication mechanism is demo-grade.
- Deterministic dev identities remain development identities, not production IAM.

## Consequences & Future Considerations

### Explicit Non-Claims (D8)
Meridian is NOT claiming:
- MFA, SSO, production IdP integration, or password authentication.
- Account lockout, rate limiting, or production TLS infrastructure.
- Compliance certification, automatic credential rotation, or protection from a compromised privileged operator / database / stolen bearer token before expiry.

Authentication introduces no new agent capability. The human-in-the-loop boundary remains unchanged. Agents/LLMs do not determine identity or authorization.

### Security / AML Boundary
The boundary remains: Observed Fact → Derived Signal → Interpretation → Recommendation.
Authentication and authorization are deterministic infrastructure concerns. LLM output MUST NEVER be an authorization signal. No authentication change may enable autonomous AML conclusions, autonomous suspicious-activity determinations, account freezing/closure, SAR filing, irreversible financial actions, or customer accusations.

### Task 20 Consequences
Task 20 will implement this model, requiring changes to:
- Token credential table & migration.
- Identity/auth module & API authentication dependency.
- `DecisionRequest` change (removing `actor_user_id`).
- 401/403 behavior & visibility enforcement.
- Authenticated audit actor.
- Development credential provisioning.
- Streamlit authentication changes.
- Tests & required durable documentation reconciliation (`SECURITY.md`).

*(Task 19 does not modify these implementation files.)*
