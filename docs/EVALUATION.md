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

The currently implemented amount deviation risk signal is a PROTOTYPE heuristic (`value = deviation_multiple`). This explicit pass-through formula is an unvalidated placeholder mimicking the `confidence_threshold` pattern in §4; it was not derived from any ML evaluation or tuning process and its predictive utility is currently unknown.

### Amount Deviation Baseline (PROTOTYPE)

**Disclaimer:** No threshold was selected. No calibration was performed. No risk-level mapping was derived. The amount-deviation implementation was unchanged. The dataset is synthetic. Small sample size limits inference. v0.1 AUC=1.0 is a fixture-construction artifact and is not evidence of predictive utility.

**Metadata:**
* **Methodology Tier:** PROTOTYPE
* **Fixture Version:** 0.1
* **Generator Version:** 0.1
* **Seed:** baseline_seed
* **Split Methodology:** md5(seed_fix_id) % 2 even=train odd=eval

**Exclusions:**
* `worked_example`: 1
* `runtime_edge_case`: 1

**ROC-AUC Results:**
* **Train:** 1.0 (7 positive, 4 negative)
* **Validation (Eval):** 1.0 (5 positive, 2 negative)
* **Pooled:** 1.0 (12 positive, 6 negative)

**Per-Scenario Statistics:**
* **structuring:** n=3, computed=3, unknown=0, min=1.288135593220338983050847458, median=1.288135593220338983050847458, max=1.288135593220338983050847458
* **rapid_movement:** n=3, computed=3, unknown=0, min=50, median=50, max=50
* **circular_transfer:** n=3, computed=3, unknown=0, min=9.8, median=9.8, max=9.8
* **mule_account_chain:** n=3, computed=3, unknown=0, min=5, median=5, max=5
* **clean_control:** n=6, computed=6, unknown=0, min=0.09090909090909090909090909091, median=0.0909090909090909090909090909, max=0.09090909090909090909090909091

**Reproduction Command:**
```bash
export $(cat .env | xargs) && PYTHONPATH=$(pwd)/src .venv/bin/python -m meridian.fixtures.amount_deviation_baseline
```

### Single-Signal Baselines on Corpus v0.3 (PROTOTYPE)

**Reproduction Command:**
```bash
export $(cat .env | xargs) && PYTHONPATH=$(pwd)/src .venv/bin/python -m meridian.fixtures.signal_baseline
```
Note: The v0.3 evaluation fixture corpus is assumed to already exist in the database.
You can load it by using the same test loading pattern used in the `tests/test_fixtures_v03.py` tests.

**Disclaimer:**
* methodology tier is PROTOTYPE
* no threshold was derived
* no calibration was derived
* no risk level was derived
* no signal combination was derived
* no signal ranking was derived
* signals were unchanged
* data is synthetic
* n is small
* report n_positive and n_negative
* Hanley-McNeil SE is approximate
* v0.1 AUC=1.0 remains a fixture-construction artifact
* no v0.2 velocity or beneficiary-age results exist and must not be quoted
* v0.2 is not suitable for those measurements
* circular_transfer and mule_account_chain were not designed to be detected by these three signals

**Metadata:**
* **Fixture Version:** 0.3
* **Generator Version:** 0.3
* **Seed:** baseline_seed
* **Split Methodology:** stable sorted alternating

**Signal directions:**
Signal directions were fixed before measurement:
* `amount_deviation`: HIGHER = more suspicious
* `transaction_velocity`: HIGHER = more suspicious
* `beneficiary_age`: LOWER age = more suspicious

**What drives the numbers:**
**Amount deviation**
* overlapping ratio ranges
* hard-negative control subtypes

**Velocity**
* structuring intentionally has multi-transaction behavior
* busy_legitimate provides overlap
* rapid_movement, circular_transfer and mule_account_chain have no extra outgoing transactions

**Beneficiary age**
* state/age distribution is constructed independently of class
* departures from approximately 0.5 are therefore attributable to sampling and unknown handling, not evidence of detection ability

**Observed Output (VERBATIM):**
```json
{"exclusions":{"insufficient_history":1,"worked_example":1},"metadata":{"explicit_disclaimer":"No threshold was derived. No calibration was derived. No risk level was derived. No signal combination was derived. Signals were not modified. Data is synthetic. Sample size is small. Results reflect fixture design parameters. Results are not evidence of real-world AML detection performance.","fixture_version":"0.3","generator_version":"0.3","methodology_tier":"PROTOTYPE","seed":"baseline_seed","signal_directions":{"amount_deviation":"HIGHER","beneficiary_age":"LOWER","transaction_velocity":"HIGHER"},"split_methodology":"stable sorted alternating"},"signals":{"amount_deviation":{"auc_results":{"eval":{"auc":0.703125,"auc_se_hanley_mcneil":0.09878,"n_negative":12,"n_positive":16,"unknown_excluded":true},"pooled":{"auc":0.701823,"auc_se_hanley_mcneil":0.069262,"n_negative":24,"n_positive":32,"unknown_excluded":true},"train":{"auc":0.729167,"auc_se_hanley_mcneil":0.095329,"n_negative":12,"n_positive":16,"unknown_excluded":true}},"per_scenario_statistics":{"circular_transfer/baseline":{"max":"1.409999579669886002048556240","median":"1.170001445715326306520136072","min":"0.6099991300352803047896231183","n":4,"n_computed":4,"n_unknown":0},"circular_transfer/elevated":{"max":"13.50999989567140666242397054","median":"11.43999877902896218991690499","min":"8.579998958640678966277313987","n":4,"n_computed":4,"n_unknown":0},"clean_control/busy_legitimate":{"max":"1.460000419466019756849530548","median":"1.104999851321399536561135671","min":"0.6400017369376467704444955596","n":8,"n_computed":8,"n_unknown":0},"clean_control/large_legitimate":{"max":"11.13002124306174193106283835","median":"6.46500883298685760161933171","min":"4.100000370508968169574544552","n":8,"n_computed":8,"n_unknown":0},"clean_control/typical":{"max":"1.320001265702623168686517103","median":"0.759999570339729666237082732","min":"0.5499995746461249101923295548","n":8,"n_computed":8,"n_unknown":0},"mule_account_chain/baseline":{"max":"1.870001125988974499796632603","median":"1.660001420055136806178197188","min":"0.7299993254744493689218304243","n":4,"n_computed":4,"n_unknown":0},"mule_account_chain/elevated":{"max":"11.17997292990573463628160577","median":"8.61499007988002865613241352","min":"4.809997196811931299583207642","n":4,"n_computed":4,"n_unknown":0},"rapid_movement/baseline":{"max":"1.760000115610361289604677595","median":"1.209997687829526933440477902","min":"0.6000004667346543479833562422","n":4,"n_computed":4,"n_unknown":0},"rapid_movement/elevated":{"max":"13.71998033033725585886645013","median":"10.51499489406607805569628773","min":"5.899998364538121825027736905","n":4,"n_computed":4,"n_unknown":0},"structuring/baseline":{"max":"1.770000500579293573795181815","median":"1.335000069427555834126048454","min":"0.8499997568139622389563693298","n":4,"n_computed":4,"n_unknown":0},"structuring/elevated":{"max":"11.45999696238057545672367878","median":"8.69000152972856764249864866","min":"4.850003340935061660070993926","n":4,"n_computed":4,"n_unknown":0}}},"beneficiary_age":{"auc_results":{"eval":{"auc":0.521368,"auc_se_hanley_mcneil":0.127534,"n_negative":9,"n_positive":13,"unknown_excluded":true},"pooled":{"auc":0.396991,"auc_se_hanley_mcneil":0.089586,"n_negative":18,"n_positive":24,"unknown_excluded":true},"train":{"auc":0.252525,"auc_se_hanley_mcneil":0.114618,"n_negative":9,"n_positive":11,"unknown_excluded":true}},"per_scenario_statistics":{"circular_transfer/baseline":{"max":"19008000","median":"3888000","min":"216000","n":4,"n_computed":3,"n_unknown":1},"circular_transfer/elevated":{"max":"16588800","median":"8380800","min":"46800","n":4,"n_computed":3,"n_unknown":1},"clean_control/busy_legitimate":{"max":"24796800","median":"2.80080E+6","min":"111600","n":8,"n_computed":6,"n_unknown":2},"clean_control/large_legitimate":{"max":"33264000","median":"1.47600E+6","min":"108000","n":8,"n_computed":6,"n_unknown":2},"clean_control/typical":{"max":"27734400","median":"1.96740E+6","min":"140400","n":8,"n_computed":6,"n_unknown":2},"mule_account_chain/baseline":{"max":"29116800","median":"26438400","min":"187200","n":4,"n_computed":3,"n_unknown":1},"mule_account_chain/elevated":{"max":"32832000","median":"12096000","min":"39600","n":4,"n_computed":3,"n_unknown":1},"rapid_movement/baseline":{"max":"6048000","median":"4060800","min":"205200","n":4,"n_computed":3,"n_unknown":1},"rapid_movement/elevated":{"max":"32832000","median":"31881600","min":"212400","n":4,"n_computed":3,"n_unknown":1},"structuring/baseline":{"max":"21945600","median":"4924800","min":"176400","n":4,"n_computed":3,"n_unknown":1},"structuring/elevated":{"max":"9417600","median":"4924800","min":"172800","n":4,"n_computed":3,"n_unknown":1}},"unknown_reasons":{"no matching beneficiary record for this customer and destination account":14}},"transaction_velocity":{"auc_results":{"eval":{"auc":0.484375,"auc_se_hanley_mcneil":0.112286,"n_negative":12,"n_positive":16,"unknown_excluded":true},"pooled":{"auc":0.442057,"auc_se_hanley_mcneil":0.078427,"n_negative":24,"n_positive":32,"unknown_excluded":true},"train":{"auc":0.398438,"auc_se_hanley_mcneil":0.110428,"n_negative":12,"n_positive":16,"unknown_excluded":true}},"per_scenario_statistics":{"circular_transfer/baseline":{"max":"1","median":"1","min":"1","n":4,"n_computed":4,"n_unknown":0},"circular_transfer/elevated":{"max":"1","median":"1","min":"1","n":4,"n_computed":4,"n_unknown":0},"clean_control/busy_legitimate":{"max":"5","median":"3.5","min":"2","n":8,"n_computed":8,"n_unknown":0},"clean_control/large_legitimate":{"max":"2","median":"1","min":"1","n":8,"n_computed":8,"n_unknown":0},"clean_control/typical":{"max":"2","median":"1","min":"1","n":8,"n_computed":8,"n_unknown":0},"mule_account_chain/baseline":{"max":"1","median":"1","min":"1","n":4,"n_computed":4,"n_unknown":0},"mule_account_chain/elevated":{"max":"1","median":"1","min":"1","n":4,"n_computed":4,"n_unknown":0},"rapid_movement/baseline":{"max":"1","median":"1","min":"1","n":4,"n_computed":4,"n_unknown":0},"rapid_movement/elevated":{"max":"1","median":"1","min":"1","n":4,"n_computed":4,"n_unknown":0},"structuring/baseline":{"max":"6","median":"4.5","min":"2","n":4,"n_computed":4,"n_unknown":0},"structuring/elevated":{"max":"6","median":"5.5","min":"3","n":4,"n_computed":4,"n_unknown":0}}}}}
```

---

## 3. Graph Evaluation

**Metrics:** suspicious-network detection precision/recall against known synthetic patterns (e.g., planted mule-account chains), community-detection quality (e.g., modularity, or agreement with planted ground-truth clusters).

**Method:** synthetic data generation should include deliberately planted suspicious subgraphs (structuring rings, circular transfers, mule chains) with known ground truth, so GraphAgent output can be scored against a known answer, not just eyeballed.

### Structure Signals Baseline (PROTOTYPE)

**Disclaimer:** Deterministic structural graph primitives (e.g., cycle detection, chain depth) have been implemented as computation-only, read-only utilities. No threshold was selected. No calibration was performed. No risk-level mapping was derived. These primitives do not assign risk scores or AML labels. Their predictive utility for identifying suspicious behavior is currently unvalidated and unmeasured.

**Metadata:**
* **Methodology Tier:** PROTOTYPE

---

## 4. RAG Evaluation

**Metrics:** retrieval precision, retrieval recall, context relevance, citation correctness, faithfulness, groundedness.

**Method:** build a small labeled query set (e.g., 20–50 alert-pattern → expected-policy-chunk pairs) against the policy corpus (`docs/DATA_AND_DATASET_STRATEGY.md`). Faithfulness/groundedness checked by verifying that report text citing a policy chunk actually reflects that chunk's content (can be partially automated via an LLM-as-judge pass, but any such automated score must be labeled as such, not presented as ground truth).

**Retrieval confidence threshold:** the minimum relevance score below which PolicyAgent returns no citation (`docs/AI_SAFETY_AND_GUARDRAILS.md` §3) must be set based on this evaluation, not picked arbitrarily — document the chosen threshold and the precision/recall tradeoff it implies.

The currently implemented threshold value is `confidence_threshold = 0.01` in `src/meridian/agents/policy/policy_agent.py`. Its methodology tier is `PROTOTYPE`. This value is explicitly an unvalidated placeholder; it was not derived from any evaluation, sample, or tuning process. The precision/recall tradeoff this threshold implies is currently unknown and unmeasured. This threshold will eventually be calibrated using the 20–50 labeled alert-pattern → expected-policy-chunk evaluation set described above. Once that evaluation exists and the threshold is properly tuned against it, its tier will be updated to `EXPERIMENTALLY_CALIBRATED`.

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

The `v0.1`, `v0.2`, and `v0.3` synthetic fixture corpora (`src/meridian/fixtures/generator.py`) produce deterministic evaluation sets.
- **v0.1:** 20 explicitly labeled scenarios, used to verify code paths. Very rigid numeric values with no variance.
- **v0.2:** 58 explicitly labeled scenarios, introducing **seeded variance** and **hard negative subtypes**.
  - **Scenario taxonomy:** structuring, rapid movement, circular transfers, mule chains, clean control (subtypes: typical, large_legitimate), and insufficient history.
  - **Subtypes and Variance:** In v0.2, scenarios are subdivided into *baseline* (typical suspicious behavior) and *elevated* (highly suspicious behavior). Clean controls include *typical* and *large_legitimate* (hard negatives with amounts resembling suspicious activity but clean topology). All generated amounts, timestamps, and UUIDs are deterministically derived from the combination of the `seed` and `fixture_id` via SHA-256 hashes, producing reproducible distributions with within-class variance rather than identical duplicate values.
- **v0.3:** 58 explicitly labeled scenarios matching v0.2's composition (8 of each class + 2 specials). Introduces beneficiary-state quotas (20% absent, 40% fresh, 40% established) applied via a common distribution independent of scenario class. Also introduces exact target-velocity generation via isolated extra transaction counts, and strictly neutral vocabulary (`large_transaction`, `new_beneficiary`, `rapid_movement`) for alert types decoupled from ground truth. Like v0.1/v0.2, v0.3 is a synthetic evaluation fixture corpus and makes no statistical independence or real-world predictive performance claim.
- **Explicit ground truth:** Each fixture explicitly declares its intended ground truth (e.g. `AML_STRUCTURING`, `CLEAN`) and evaluation target directly in its manifest.
- **Planted pattern metadata:** The specific synthetic behavior injected into the data is tracked exactly, along with the IDs of pattern members.
- **Split / pattern atomicity:** Each fixture instance acts as a fully self-contained atomic scenario mapped strictly to either `train` or `eval` deterministically via a hash-based assignment. A single pattern's data never crosses the split boundary.
- **Limitations:** While v0.2 adds intra-class variance and hard negatives, it remains synthetic. The numeric distributions do not represent a calibrated true-to-life realistic simulation.

---

## 9. What Is Explicitly Disallowed

- Publishing a metric without stating its tier and evaluation-set version.
- Publishing a resume/portfolio claim (e.g., "reduced investigation time by 90%") without a real measured basis (`PROJECT_BRIEF` §29).
- Treating an LLM-as-judge score as ground truth without labeling it as an automated proxy metric.
- Skipping evaluation for a "prototype" feature and presenting it as evaluated anyway.

---

## 10. Related Documents

`docs/AI_SAFETY_AND_GUARDRAILS.md` §5 (confidence tiers used in reports), `docs/TESTING.md` (fixture reuse for regression), `docs/DATA_AND_DATASET_STRATEGY.md` (fixture generation), `docs/DECISIONS.md` (ADR needed if evaluation methodology changes materially).
