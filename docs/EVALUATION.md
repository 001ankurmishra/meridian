# Evaluation Strategy — Project Meridian

**Read every coding session?** Conditionally — yes for any change to risk scoring, retrieval, or agent logic.

Meridian must never be evaluated by narrative claim alone ("the AI works well"). Every category below requires a real, reproducible measurement against the synthetic fixture set. No benchmark numbers may be invented, estimated, or presented before they've actually been produced by a run (`CLAUDE.md` §2).

---

## 1. Methodology Tiers (applies to every metric below)

| Tier | Meaning |
|---|---|
| PROTOTYPE | Metric computed on a small/ad hoc sample; directional only |
| EXPERIMENTALLY_CALIBRATED | Metric computed on a defined, versioned evaluation set with a documented split |
| PRODUCTION_APPROVED | Not applicable to this project's current scope — would require live-monitoring validation |

Every reported number in `docs/` or a resume/portfolio artifact must state its tier and the evaluation-set version used to produce it.

---

## 2. ML Evaluation (Risk Scoring / Anomaly Detection)

**Metrics:** precision, recall, F1, PR-AUC, ROC-AUC, false-positive rate, false-negative rate, calibration (e.g., reliability diagram / Brier score).

**Method:** evaluated against labeled synthetic patterns (AMLSim ground-truth labels where available; hand-labeled synthetic suspicious/normal patterns otherwise — `docs/DATA_AND_DATASET_STRATEGY.md`). Use a fixed train/validation/test split, versioned alongside the model.

**Reporting requirement:** any risk-scoring metric quoted anywhere in the project must include: dataset version, split methodology, and tier (§1). "PROTOTYPE, 40-case hand-labeled sample, v0.1" is an acceptable and honest label; a bare "92% precision" with no context is not acceptable.

---

## 3. Graph Evaluation

**Metrics:** suspicious-network detection precision/recall against known synthetic patterns (e.g., planted mule-account chains), community-detection quality (e.g., modularity, or agreement with planted ground-truth clusters).

**Method:** synthetic data generation should include deliberately planted suspicious subgraphs (structuring rings, circular transfers, mule chains) with known ground truth, so GraphAgent output can be scored against a known answer, not just eyeballed.

---

## 4. RAG Evaluation

**Metrics:** retrieval precision, retrieval recall, context relevance, citation correctness, faithfulness, groundedness.

**Method:** build a small labeled query set (e.g., 20–50 alert-pattern → expected-policy-chunk pairs) against the policy corpus (`docs/DATA_AND_DATASET_STRATEGY.md`). Faithfulness/groundedness checked by verifying that report text citing a policy chunk actually reflects that chunk's content (can be partially automated via an LLM-as-judge pass, but any such automated score must be labeled as such, not presented as ground truth).

**Retrieval confidence threshold:** the minimum relevance score below which PolicyAgent returns no citation (`docs/AI_SAFETY_AND_GUARDRAILS.md` §3) must be set based on this evaluation, not picked arbitrarily — document the chosen threshold and the precision/recall tradeoff it implies.

---

## 5. Agent Evaluation

**Metrics:** task success rate, correct tool selection rate, invalid tool-call rate, investigation completeness, unsupported-claim rate, hallucination rate, cost/latency per investigation.

**Method:** run the full fixture set (§6) through the orchestrator end-to-end; for each run, check: did the right agents get dispatched, did tool calls succeed/validate, did any finding lack supporting evidence (unsupported-claim rate — this should be **zero** given the evidence-sufficiency gate; if it isn't, that's a defect, not a metric to accept), did the reasoning chain (Fact→Signal→Interpretation→Recommendation) stay intact.

---

## 6. System Evaluation

**Metrics:** reliability (successful-completion rate across the fixture set), latency (per investigation, per agent), throughput (investigations/hour under test load), failure recovery (does the system correctly reach `INCOMPLETE_INSUFFICIENT_EVIDENCE` / `FAILED` states rather than silently corrupting state), reproducibility (does re-running the same alert against the same data/model version produce materially the same findings).

---

## 7. Human Evaluation

**Metrics:** analyst agreement (does a human reviewer agree with the AI's risk level and recommendation), evidence completeness (does the report surface everything a human would have found manually), report correctness, investigation-time reduction, usability.

**Method:** compare AI-generated investigations against a small set of hand-written reference investigations on the same synthetic fixture cases (produced by the project author role-playing an analyst, or a domain-knowledgeable reviewer, clearly labeled as such). Investigation-time-reduction claims (e.g., "reduced investigation time by X%") may only be published if actually measured on a real timed comparison — never estimated. This directly enforces `PROJECT_BRIEF` §29's own caution against inventing improvement numbers.

---

## 8. Synthetic Fixture Set

A fixed, versioned set of alert scenarios (including the worked example in `docs/PRODUCT_BRIEF.md` §5, plus additional planted-pattern cases: structuring, rapid movement, circular transfers, mule accounts, and at least one clean/non-suspicious control case) underlies all evaluation categories above. See `docs/DATA_AND_DATASET_STRATEGY.md` for generation details and `docs/TESTING.md` for how this set is also used as regression fixtures.

---

## 9. What Is Explicitly Disallowed

- Publishing a metric without stating its tier and evaluation-set version.
- Publishing a resume/portfolio claim (e.g., "reduced investigation time by 90%") without a real measured basis (`PROJECT_BRIEF` §29).
- Treating an LLM-as-judge score as ground truth without labeling it as an automated proxy metric.
- Skipping evaluation for a "prototype" feature and presenting it as evaluated anyway.

---

## 10. Related Documents

`docs/AI_SAFETY_AND_GUARDRAILS.md` §5 (confidence tiers used in reports), `docs/TESTING.md` (fixture reuse for regression), `docs/DATA_AND_DATASET_STRATEGY.md` (fixture generation), `docs/DECISIONS.md` (ADR needed if evaluation methodology changes materially).
