# Data & Dataset Strategy — Project Meridian

**Read every coding session?** Conditionally — yes for any change touching data ingestion, synthetic generation, or fixtures.

---

## 1. Core Rule

Meridian uses **only public and synthetic financial data**. Real bank customer data is never used, referenced, or implied. Every record in `customers`, `accounts`, `transactions`, `beneficiaries` carries `is_synthetic = true` (`docs/DATABASE_SCHEMA.md` §4.1) and this must be visibly labeled anywhere the data is presented — UI, reports, demo materials, README.

---

## 2. Candidate Public Datasets

| Dataset | Use | Status |
|---|---|---|
| **IBM AMLSim** | Synthetic transaction network generator with built-in laundering-pattern labels; primary source for graph/pattern fixtures | Confirmed viable — **REQUIRES VERIFICATION**: exact license terms and current repository location at implementation time (public tooling/links can change; verify before import) |
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

Every synthetic-generation run is versioned (a generator version string stored in `source` columns) so fixtures and evaluation results stay reproducible.

---

## 4. Synthetic Policy Corpus

Since real internal bank AML policy documents aren't available, the policy corpus used for RAG is either:
(a) publicly available regulatory guidance (e.g., published RBI circulars/FREE-AI framework material, EU AI Act text) used and cited as genuinely external regulatory sources, clearly distinguished from —
(b) authored synthetic "internal policy" documents, clearly labeled `is_synthetic = true` and never presented as an actual bank's real policy.

This distinction must be visible in the UI/report wherever a policy citation appears (`docs/DESIGN.md` §6) — a citation to (a) is a real regulatory reference; a citation to (b) is illustrative.

---

## 5. Data Governance

- No real PII is ever ingested into this system, under any circumstance, including "just for testing."
- Dataset provenance (source, version, license note) is tracked per import (`docs/DATABASE_SCHEMA.md` `source` columns).
- Retention: since all data is synthetic/public, no regulatory retention constraint applies; retention is governed by project/portfolio needs only (`docs/SECURITY.md` §4).

---

## 6. Related Documents

`docs/DATABASE_SCHEMA.md` §3 and §4.1 (provenance/synthetic flag), `docs/EVALUATION.md` §8 (fixture set), `docs/TESTING.md` §3 (fixtures reused for tests), `docs/PRODUCT_BRIEF.md` §5 (the canonical worked example this data must support).
