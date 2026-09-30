# Data & Dataset Strategy — Project Meridian

**Read every coding session?** Conditionally — yes for any change touching data ingestion, synthetic generation, or fixtures.

---

## 1. Core Rule

Meridian uses **only public and synthetic financial data**. Real bank customer data is never used, referenced, or implied. Every record in `customers`, `accounts`, `transactions`, `beneficiaries` carries `is_synthetic = true` (`docs/DATABASE_SCHEMA.md` §4.1) and this must be visibly labeled anywhere the data is presented — UI, reports, demo materials, README.

---

## 2. Candidate Public Datasets

| Dataset | Use | Status |
|---|---|---|
| **IBM AMLSim** | Synthetic transaction network generator with built-in laundering-pattern labels; primary source for graph/pattern fixtures | **Blocked**: During Task 1.1, the original IBM AMLSim Java/Python build process failed. Its `install.sh` required Java 8 and a globally accessible `mvn` (Maven), which were not present in the environment. Additionally, its Python environment required a very outdated `networkx==2.1` which conflicted with modern pip resolvers, and building its Mason dependency threw raw `make` and `.jar` resolution errors. As a result, the Meridian-native generator is the current bulk-data source. AMLSim can be revisited if these build/runtime blockers are resolved (e.g., via a Dockerized build process). |
| **PaySim** | Synthetic mobile-money transaction dataset; useful for transaction-volume/behavioral baseline data | Confirmed viable — same license-verification note applies |
| **Elliptic dataset** | Labeled Bitcoin transaction graph (licit/illicit); useful as an additional graph-pattern reference, though domain (crypto) differs from the bank-transfer narrative | Confirmed viable for graph-technique validation; **not** used as the primary narrative dataset since Meridian's worked example is bank-transfer-based, not crypto |
| **IEEE-CIS Fraud Detection dataset** | Card-fraud-oriented; potentially useful for ML-technique validation but domain mismatch (card fraud vs. AML) | Optional/secondary — **REQUIRES VERIFICATION** if used |

Before incorporating any dataset: verify current availability, license terms, and permitted use (research/portfolio use is generally fine for these public research datasets, but the exact license text must be checked at import time, not assumed from memory — per `CLAUDE.md` §2, "EXTERNAL" claims require verification against the source).

---

## 3. Synthetic Data Generation (Custom)

Where public datasets don't cover a needed scenario (e.g., realistic Indian-Rupee-denominated retail banking behavior matching the worked example), a custom synthetic generator produces:

- Customers, accounts, transactions, beneficiaries, merchants, devices, locations (as needed per `docs/DATABASE_SCHEMA.md` §6 deferred-entity triggers)
- **Normal behavior** baseline (typical transaction amounts/frequency per customer segment)
- **Suspicious behavior patterns**, deliberately planted with known ground truth for evaluation (`docs/EVALUATION.md` §3, §8):
  - Structuring (multiple sub-threshold transactions)
  - Rapid fund movement
  - Circular transfers
  - Mule-account chains
  - Multiple-counterparty funneling
  - Sudden behavioral change (e.g., dormant account suddenly active)

Every synthetic-generation run is versioned (e.g. `generator_version` and `fixture_version`) so fixtures and evaluation results stay reproducible.
To ensure exact byte-for-byte reproducibility across runs and environments, the generator uses:
- A fixed `ANCHOR_TIMESTAMP` (e.g., `2026-01-01T12:00:00Z`). All transaction times and event dates are derived as fixed relative `timedelta` offsets from this anchor.
- Deterministic UUIDs generated via `uuid5` using the generator seed, fixture ID, and record keys, meaning the same seed always produces the exact same primary and foreign keys.
- No dependence on system entropy, `PYTHONHASHSEED`, or environmental timezone variations.

**Important:** This synthetic fixture corpus (v0.1) is explicitly built for functional testing and orchestration pathways. It does NOT claim to represent real-world AML typologies and its detection performance on these fixtures does not constitute a real-world AML detection capability claim.

---

## 4. Synthetic Policy Corpus

Since real internal bank AML policy documents aren't available, the policy corpus used for RAG is either:
(a) publicly available regulatory guidance (e.g., published RBI circulars/FREE-AI framework material, EU AI Act text) used and cited as genuinely external regulatory sources, clearly distinguished from —
(b) authored synthetic "internal policy" documents, clearly labeled `is_synthetic = true` and never presented as an actual bank's real policy.

This distinction must be visible in the UI/report wherever a policy citation appears (`docs/DESIGN.md` §6) — a citation to (a) is a real regulatory reference; a citation to (b) is illustrative.

A four-document synthetic internal-policy corpus v1 now exists. Documents are loaded by `meridian.loader.main` and are marked `is_synthetic = true`. No `regulatory_guidance` documents are included yet; regulatory guidance remains deferred pending EXTERNAL source verification.

---

## 5. Data Governance

- No real PII is ever ingested into this system, under any circumstance, including "just for testing."
- Dataset provenance (source, version, license note) is tracked per import (`docs/DATABASE_SCHEMA.md` `source` columns).
- Retention: since all data is synthetic/public, no regulatory retention constraint applies; retention is governed by project/portfolio needs only (`docs/SECURITY.md` §4).

---

## 6. Development Identities

A minimal deterministic seed provides two users for local development and demonstration:
- `dev.analyst.1@meridian.local` (role: `analyst`, UUID `e26bbc72-e869-50f5-b62b-f1e51703ddc5`)
- `dev.senior.analyst.1@meridian.local` (role: `senior_analyst`, UUID `e54f2839-b7bb-5e8f-bc41-67b7f97451a0`)

These UUIDs are deterministically generated using `uuid.uuid5(uuid.NAMESPACE_OID, "<name>")`.
When the database is seeded (`meridian.loader.dev_users`), existing user rows with these IDs are verified. The seed validates existing identity data rather than blindly skipping conflicts. Any mismatch in email or role fails loudly (throws an exception).
**IMPORTANT**: These identities are for local/demo use only and do NOT constitute an authentication system.

---

## 7. Related Documents

`docs/DATABASE_SCHEMA.md` §3 and §4.1 (provenance/synthetic flag), `docs/EVALUATION.md` §8 (fixture set), `docs/TESTING.md` §3 (fixtures reused for tests), `docs/PRODUCT_BRIEF.md` §5 (the canonical worked example this data must support).
