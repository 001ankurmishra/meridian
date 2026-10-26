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

**Reproduction Command:**
```bash
export $(cat .env | xargs) && PYTHONPATH=$(pwd)/src .venv/bin/python -m meridian.fixtures.graph_structure_baseline
```
Note: The v0.4 evaluation fixture corpus is assumed to already exist in the database.
You can load it by using the same test loading pattern used in the `tests/test_graph_structure_baseline.py` tests.

**Disclaimer:** Deterministic structural graph primitives (e.g., cycle detection, chain depth) have been implemented as computation-only, read-only utilities. No threshold was selected. No calibration was performed. No risk-level mapping was derived. These primitives do not assign risk scores or AML labels. Their predictive utility for identifying suspicious behavior is currently unvalidated and unmeasured.

**Metadata:**
* **Methodology Tier:** PROTOTYPE
* **Fixture Version:** 0.4
* **Generator Version:** 0.4
* **Seed:** baseline_seed

**Metric Interpretation Note:**
These signals measure deterministic structural fidelity against an oracle, not probabilistic predictive utility. Therefore ROC-AUC is mathematically inappropriate. Exact match rate and MAE are reported.

**Limitation on Depth-4 Boundary:**
The v0.4 corpus currently has a maximum observed outbound chain depth of 3. Therefore, the Task 10 `max_hops=4` boundary is not exercised by the current corpus. This result should not be interpreted as evidence of correct behavior at depth 4.

**Observed Output (VERBATIM):**
```json
{"exclusions":{},"metadata":{"explicit_disclaimer":"No threshold was selected. No calibration was performed. No risk-level mapping was derived. These primitives do not assign risk scores. Their predictive utility for AML behavior remains uncalibrated.","fixture_version":"0.4","generator_version":"0.4","methodology_tier":"PROTOTYPE","metric_interpretation_note":"These signals measure deterministic structural fidelity against an oracle, not probabilistic predictive utility. Therefore ROC-AUC is mathematically inappropriate. Exact match rate and MAE are reported.","seed":"baseline_seed"},"signals":{"directed_cycle":{"per_scenario_statistics":{"circular_transfer/baseline":{"fn":0,"fp":0,"n":4,"n_found":4,"n_not_found":0,"n_truncated":0,"tn":0,"tp":4},"circular_transfer/elevated":{"fn":0,"fp":0,"n":4,"n_found":4,"n_not_found":0,"n_truncated":0,"tn":0,"tp":4},"clean_control/busy_legitimate":{"fn":0,"fp":0,"n":8,"n_found":0,"n_not_found":8,"n_truncated":0,"tn":8,"tp":0},"clean_control/large_legitimate":{"fn":0,"fp":0,"n":8,"n_found":0,"n_not_found":8,"n_truncated":0,"tn":8,"tp":0},"clean_control/typical":{"fn":0,"fp":0,"n":8,"n_found":0,"n_not_found":8,"n_truncated":0,"tn":8,"tp":0},"insufficient_history/baseline":{"fn":0,"fp":0,"n":1,"n_found":0,"n_not_found":1,"n_truncated":0,"tn":1,"tp":0},"mule_account_chain/baseline":{"fn":0,"fp":0,"n":4,"n_found":0,"n_not_found":4,"n_truncated":0,"tn":4,"tp":0},"mule_account_chain/elevated":{"fn":0,"fp":0,"n":4,"n_found":0,"n_not_found":4,"n_truncated":0,"tn":4,"tp":0},"rapid_movement/baseline":{"fn":0,"fp":0,"n":4,"n_found":0,"n_not_found":4,"n_truncated":0,"tn":4,"tp":0},"rapid_movement/elevated":{"fn":0,"fp":0,"n":4,"n_found":0,"n_not_found":4,"n_truncated":0,"tn":4,"tp":0},"structuring/baseline":{"fn":0,"fp":0,"n":4,"n_found":0,"n_not_found":4,"n_truncated":0,"tn":4,"tp":0},"structuring/elevated":{"fn":0,"fp":0,"n":4,"n_found":0,"n_not_found":4,"n_truncated":0,"tn":4,"tp":0},"worked_example/baseline":{"fn":0,"fp":0,"n":1,"n_found":0,"n_not_found":1,"n_truncated":0,"tn":1,"tp":0}},"structural_fidelity":{"confusion_matrix":{"FN":0,"FP":0,"TN":50,"TP":8},"exact_match_rate":1.0,"n_applicable":58,"n_exact_match":58,"truncation_rate":0.0}},"outbound_chain_depth":{"per_scenario_statistics":{"circular_transfer/baseline":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"circular_transfer/elevated":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"clean_control/busy_legitimate":{"exact_matches":8,"mean_absolute_error":0.0,"n":8,"n_computed":8,"n_truncated":0},"clean_control/large_legitimate":{"exact_matches":8,"mean_absolute_error":0.0,"n":8,"n_computed":8,"n_truncated":0},"clean_control/typical":{"exact_matches":8,"mean_absolute_error":0.0,"n":8,"n_computed":8,"n_truncated":0},"insufficient_history/baseline":{"exact_matches":1,"mean_absolute_error":0.0,"n":1,"n_computed":1,"n_truncated":0},"mule_account_chain/baseline":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"mule_account_chain/elevated":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"rapid_movement/baseline":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"rapid_movement/elevated":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"structuring/baseline":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"structuring/elevated":{"exact_matches":4,"mean_absolute_error":0.0,"n":4,"n_computed":4,"n_truncated":0},"worked_example/baseline":{"exact_matches":1,"mean_absolute_error":0.0,"n":1,"n_computed":1,"n_truncated":0}},"structural_fidelity":{"exact_match_rate":1.0,"mean_absolute_error":0.0,"n_applicable":58,"n_exact_match":58,"truncation_rate":0.0}}}}
```

---

## 4. RAG Evaluation

**Metrics:** retrieval precision, retrieval recall, context relevance, citation correctness, faithfulness, groundedness.

**Method:** build a small labeled query set (e.g., 20–50 alert-pattern → expected-policy-chunk pairs) against the policy corpus (`docs/DATA_AND_DATASET_STRATEGY.md`). Faithfulness/groundedness checked by verifying that report text citing a policy chunk actually reflects that chunk's content (can be partially automated via an LLM-as-judge pass, but any such automated score must be labeled as such, not presented as ground truth).

**Retrieval confidence threshold:** the minimum relevance score below which PolicyAgent returns no citation (`docs/AI_SAFETY_AND_GUARDRAILS.md` §3) must be set based on this evaluation, not picked arbitrarily — document the chosen threshold and the precision/recall tradeoff it implies.

The currently implemented threshold value is `confidence_threshold = 0.01` in `src/meridian/agents/policy/policy_agent.py`. Its methodology tier is `PROTOTYPE`. This value is explicitly an unvalidated placeholder; it was not derived from any evaluation, sample, or tuning process. The precision/recall tradeoff this threshold implies is currently unknown and unmeasured. This threshold will eventually be calibrated using the 20–50 labeled alert-pattern → expected-policy-chunk evaluation set described above. Once that evaluation exists and the threshold is properly tuned against it, its tier will be updated to `EXPERIMENTALLY_CALIBRATED`.

ADR-0009 (accepted by Ankur 2026-10-26) adds a query-level maximum-cosine
threshold of 0.620313, selected only from the labeled DEV examples. The original
RRF threshold and ranking are unchanged. This added gate is PROTOTYPE, not
calibrated; it cannot establish policy applicability or validate each citation.
The paired baseline/gate HELDOUT configuration is locked in
`docs/evaluation/policy_retrieval_eval_v1.plan.json` before measurement.

### RAG evaluation protocol (policy_retrieval_eval_v1) — FROZEN 2026-10-25; locked measurement recorded

> **Protocol Status:** FROZEN by explicit approval from Ankur on 2026-10-25. No measurement performed at freeze.
> Approval and both reviewed/frozen payload hashes are recorded in `docs/evaluation/policy_retrieval_eval_v1.freeze.json`. Frozen canonical SHA-256: `993af9703de5b147a5f34ffa4d5bf01eafa025738915a3b0be940199aa78e053`. Labels are maintainer-approved, not independently validated.
> Passing automated integrity tests proves structure, binding, and mathematical validity only, NOT that human or AI judgments are substantively correct.

#### 1. Protocol Metadata and Preconditions
* **Methodology Tier:** PROTOTYPE
* **Evaluation Version:** `policy_retrieval_eval_v1`
* **Seed:** `policy_retrieval_eval_v1`
* **Corpus Identifier:** `POLICY_CORPUS_V1` (4 documents, 10 chunks)
* **Model Name:** `BAAI/bge-small-en-v1.5`
* **Model Snapshot:** `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a` (pinned for model and tokenizer; evaluation rejects revision mismatch)
* **Retrieval Parameters:** `retrieval_k = 60`, `retrieval_top_k = 5`
* **A0 Tie-Break Contract:** RRF fused ranking total order: items are ordered by `(rrf_score DESC, document_title ASC, document_version ASC, chunk_index ASC, chunk_id ASC)`; SQL title/version use C collation. Logical reload stability requires unique title/version/index tuples.
* **Chunk Identity:** Chunks are referenced exclusively by literal tuples: `(title, version, chunk_index, text_sha256)`. Database UUIDs (`chunk_id`) are never used for evaluation ground truth.

#### 2. Cohorts and Statuses
* **Cohort C1 (PRIMARY, n=3):** Production query path (`large_transaction`, `new_beneficiary`, `rapid_movement`), where `alert_type` is passed verbatim to policy retrieval. Descriptive only. Never split (`split = NONE`).
* **Cohort C2 (PROVISIONAL, n=5):** Legacy query strings (`AML_GENERAL`, `AML_STRUCTURING`, `AML_RAPID_MOVEMENT`, `AML_CIRCULAR`, `AML_MULE`) present in the legacy fixture generator. This protocol does not claim the legacy workflow is supported; inclusion in runtime evaluation requires maintainer confirmation. Never split (`split = NONE`). Evaluated strictly by literal meaning; applicability is `UNDETERMINED` where literal meaning is not an unambiguous investigative subject; borderline flags and notes are assigned where in doubt. Missing corpus coverage is never relabeled as "no applicable policy". All C2 queries carry abstention `NOT_ASSESSED`.
* **Cohort C3 (ROBUSTNESS, n=11):** Out-of-domain robustness probes. Arbitrary non-empty alert types are production-reachable. Contains 10 out-of-domain queries (e.g. `zzzz qqqq`, `weather forecast for tomorrow`, `chocolate cake recipe`, etc.) labeled `NOT_APPLICABLE_OUT_OF_DOMAIN`, `OUT_OF_DOMAIN`, and `SHOULD_ABSTAIN`. Contains the empty string `""` exactly once, labeled `UNDETERMINED`, `NOT_COVERED`, and `NOT_ASSESSED`, with rationale noting that alert intake rejects empty or whitespace `alert_type` at the intake validation boundary so it serves as a behavior probe only. Generic words are not labeled as negatives.
* **Cohort C4 (EXPLORATORY, n=20):** Authored paraphrase queries (>=3 per each of the four corpus topics: large transaction review, new beneficiary review, rapid movement, and evidence/documentation standards) and >=4 in-domain coverage-gap queries (applicable financial investigation subjects with no matching procedure in the synthetic corpus, labeled `APPLICABLE` + `NOT_COVERED` or `PARTIALLY_COVERED` + `NOT_ASSESSED`, with grade-1 notes where supporting guidance exists). Never mix C4 into C1 metrics.
* **Total Query Count:** 39 queries (within the required [38, 50] range).

#### 3. Split Rules
* **C1 and C2:** `split = NONE`.
* **C3 and C4:** Assigned deterministically via `assign_split(seed, query_id) = SHA-256(f"{seed}:{query_id}")` first byte parity (even = DEV, odd = HELDOUT), yielding >= 4 DEV and >= 4 HELDOUT in each cohort (C3: 5 DEV, 6 HELDOUT; C4: 9 DEV, 11 HELDOUT).
* **Usage Policy:** DEV set only is permitted for any future gate exploration or threshold calibration; HELDOUT is measured once per protocol version; tuning on HELDOUT voids the evaluation set.

#### 4. Four-Field Label Model and Grade Rubric
Every query is labeled across four dimensions:
1. `policy_applicability` ∈ {`APPLICABLE`, `NOT_APPLICABLE_OUT_OF_DOMAIN`, `UNDETERMINED`}: Domain judgment derived from the query's meaning alone, independent of synthetic corpus contents and of chunk grades. `APPLICABLE` = names/describes a subject a financial investigation procedure would in principle govern. `NOT_APPLICABLE_OUT_OF_DOMAIN` = no investigation subject. `UNDETERMINED` = meaning not established by query alone (opaque legacy strings, generic words, empty string).
2. `corpus_coverage` ∈ {`COVERED`, `PARTIALLY_COVERED`, `NOT_COVERED`, `OUT_OF_DOMAIN`}: Labeler assertion about the synthetic corpus, cross-checked against chunk grades.
3. `abstention_ground_truth` ∈ {`SHOULD_RETRIEVE`, `SHOULD_ABSTAIN`, `NOT_ASSESSED`}: Correct system decision for evaluation purposes only (never an input to labeling).
4. `judgments`: Exactly one `Judgment(chunk_ref, grade ∈ {0,1,2}, note, borderline)` per chunk for all 10 chunks in the corpus.
   * **Grade 2:** The chunk text itself states a procedure or standard specific to this query's subject.
   * **Grade 1:** The chunk text provides substantive supporting guidance an analyst handling this query would apply; a non-empty `note` naming the specific supporting element is REQUIRED for every grade 1.
   * **Grade 0:** Otherwise. Generic boilerplate (e.g. the illustrative synthetic policy disclaimer) never earns a grade.
   * **Pairwise Rule:** No document receives a blanket grade across queries — each (query, chunk) pair is judged independently.
   * **Borderline Flag:** `borderline = True` requires an explanatory note (<= 200 characters).
   * **Applicability Invariant:** Absence of a grade-2 chunk or lack of a matching synthetic document never establishes non-applicability.

#### 5. Validation Rules (V1–V8)
The validator enforces these invariants without deriving applicability or abstention from chunk grades:
* **V1:** `applicability = NOT_APPLICABLE_OUT_OF_DOMAIN` ⇒ `coverage = OUT_OF_DOMAIN`, all grades 0, `cohort = C3`.
* **V2:** `coverage = OUT_OF_DOMAIN` ⇒ `applicability = NOT_APPLICABLE_OUT_OF_DOMAIN`.
* **V3:** `coverage = COVERED` iff some grade == 2; `PARTIALLY_COVERED` iff no grade 2 and some grade 1; `NOT_COVERED` ⇒ all grades 0 and `applicability` ∈ {`APPLICABLE`, `UNDETERMINED`}.
* **V4:** `SHOULD_ABSTAIN` ⇒ `applicability = NOT_APPLICABLE_OUT_OF_DOMAIN`, `coverage = OUT_OF_DOMAIN`, `cohort = C3`. A missing grade-2 chunk or coverage `NOT_COVERED` NEVER implies `SHOULD_ABSTAIN` or non-applicability.
* **V5:** `SHOULD_RETRIEVE` ⇒ `applicability = APPLICABLE`, `coverage = COVERED`, `cohort` ∈ {`C1`, `C4`}.
* **V6:** `applicability = APPLICABLE` with `coverage` ∈ {`NOT_COVERED`, `PARTIALLY_COVERED`} ⇒ `abstention = NOT_ASSESSED`.
* **V7:** `applicability = UNDETERMINED` ⇒ `NOT_ASSESSED`; every `C2` query ⇒ `NOT_ASSESSED`.
* **V8:** every `C3` query with `NOT_APPLICABLE_OUT_OF_DOMAIN` ⇒ `SHOULD_ABSTAIN`.

#### 6. Metrics and Expected Random Baselines
The evaluation metrics and closed-form random baselines are defined verbatim below:

N = chunk count. Ranking = total order from the A0 contract. R = number of relevant chunks: strict relevance = grade 2 (R2), lenient = grade>=1 (R1+). Queries with R=0 are excluded from that relevance definition's metrics; queries with IDCG=0 excluded from nDCG; exclusion counts reported. Hit@k, Precision@k=(#rel in top k)/k, Recall@k=(#rel in top k)/R, RR=1/rank of first relevant (MRR = mean), DCG@k = sum_{i=1..k} grade(pi_i)/log2(i+1) with linear gains, nDCG@k = DCG@k/IDCG@k (IDCG = DCG of grades sorted descending), k ∈ {1,3,5}. Random-ordering expectations (uniform over all N! orderings; C(a,b)=0 if b>a): E[Precision@k]=R/N; E[Recall@k]=k/N; E[Hit@k]=1 − C(N−R,k)/C(N,k); E[RR]=sum_{j=1..N−R+1}(1/j)*C(N−j,R−1)/C(N,R); E[nDCG@k]=((G/N)*sum_{i=1..k}1/log2(i+1))/IDCG@k with G=sum of grades. Method: all but nDCG in exact rational arithmetic (fractions.Fraction, math.comb); nDCG with math.log2 float64 reported to 6 decimals. Cohort baseline = unweighted mean of per-query baselines over the same included queries; "lift" = observed mean − baseline mean; cohorts never pooled; no confidence intervals, no significance claims, no ROC-AUC, no F1. Worked example (N=10,R=3): E[P@k]=0.3, E[R@5]=0.5, E[Hit@5]=11/12, E[RR]=3601/6720≈0.535863; plus an nDCG example (grades: one 2, two 1, rest 0, k=5; expected ≈0.3767 — compute with your test oracle and quote the exact 6-decimal value; if it differs from 0.3767 beyond rounding, report it).

*Note on Worked Example nDCG:* Computed via the closed-form oracle, the exact 6-decimal expectation for the worked example (vector with one 2, two 1s, seven 0s, $N=10$, $k=5$) is `0.376688` (which rounds to `0.3767` at 4 decimal places).

#### 7. Abstention Evaluation Definition
* **System Decision:** The current production output of `retrieve_policy_evidence`.
* **Reported Metrics:**
  * False-citation rate on C3 `SHOULD_ABSTAIN` queries.
  * Abstention rate on `SHOULD_RETRIEVE` queries.
  * Descriptive top-1 and top-5-min RRF score tables.
  * Separate reporting for `SHOULD_RETRIEVE`, `SHOULD_ABSTAIN`, and `NOT_ASSESSED`.
  * `NOT_ASSESSED` queries are strictly excluded from accuracy-style counts.

#### 8. Structural Reachability Property (Derived from Code, Not Measured)
The semantic retrieval component returns an ordered list that ranks every chunk in the corpus.
In Reciprocal Rank Fusion (RRF) with $k = 60$, any chunk appearing in the semantic ranking at position $r \in [1, 5]$ receives an RRF score contribution of:
$$\text{RRF score} \ge \frac{1}{60 + 5} = \frac{1}{65} \approx 0.015385 > 0.01$$
Because this contribution exceeds the current threshold value of `confidence_threshold = 0.01`, for any non-empty corpus containing at least 5 chunks, every top-5 fused result will have a score strictly greater than 0.01.
Therefore, the current production threshold cannot yield `PolicyEvidenceInsufficient` on a non-empty corpus.
This property is **DERIVED FROM CODE, NOT MEASURED**. The future baseline measurement task must empirically verify this property against the database.

#### 9. Architectural Boundaries and Governance
* **No Threshold Derived:** No threshold has been selected, tuned, or calibrated.
* **ADR Required for Changes:** Any relevance gate or new retrieval diagnostics is a retrieval-architecture change requiring an ADR prior to implementation.
* **Prohibited Claims:** No claims may be made regarding measured retrieval quality, statistical significance, calibration, or operational effectiveness until maintainer approval and baseline execution.

#### 10. Known Limitations
1. **Corpus Size:** With $N=10$ synthetic policy chunks, chance recall is high ($E[\text{Recall}@5] = 0.5$ for any relevant chunk under uniform random ordering).
2. **Labeler Provenance:** Labels were created with AI assistance and approved by Ankur for the recorded review hash. This is maintainer review, not independent validation.
3. **Descriptive Cohorts:** Cohort C1 ($n=3$) and C2 ($n=5$) are small and descriptive only; C2 is provisional.
4. **Tokenizer Dependency:** Chunking depends on cached tokenizer files (`transformers.AutoTokenizer` for `BAAI/bge-small-en-v1.5`).
5. **Split Granularity Limitation:** DEV/HELDOUT assignment hashes individual query IDs (`assign_split(seed, query_id)`). Related paraphrases of the same alert topic may therefore occur in both splits. This evaluates query-level holdout behavior, not generalization to independent scenario families. Grouped scenario-family splitting is deferred to a future protocol revision.

---

## 5. Entity Resolution Evaluation

### ER evaluation protocol (v0.5, FROZEN before any measurement)

* evaluation-set version = 0.5
* tier = PROTOTYPE
* this is generator-defined structural fidelity, not real-world ER performance
* a candidate link is not an identity determination

### Evaluation universe

The evaluation universe is every unordered pair of customers in the evaluated corpus.

`true_match_pairs` from the v0.5 manifest are the positive ground-truth pairs.

Every unordered customer pair not present in `true_match_pairs` is negative ground truth.

### Metrics

* TP = predicted candidate link and positive ground truth
* FP = predicted candidate link and negative ground truth
* FN = positive ground truth pair for which no candidate link is produced
* TN = negative ground truth pair for which no candidate link is produced

Precision:

`TP / (TP + FP)`

Recall:

`TP / (TP + FN)`

If a denominator is zero, report the metric as NULL.

### Stratification

Recall stratification is required by:

1. `variant_transforms`
2. `within_adr_v1_scope`

* `variant_transform(s)` = how the identity relationship was constructed.
* `within_adr_v1_scope` = whether the accepted ADR-0006 D1 rule is expected to resolve that relationship.

### FP/FN reporting

FP and FN listings with their fixture/category identifiers and applicable ground-truth category information are required.

### Abstention accounting

Customers ineligible for matching because of missing/empty required fields must be accounted for by reason.

At minimum distinguish:

* missing name
* empty/whitespace-only normalized name
* missing DOB

### Accuracy and other metrics

* accuracy MUST NOT be a headline metric because TN dominates the pairwise universe.
* NO ROC-AUC.
* NO F1.
* NO thresholds.
* NO aggregate risk score.
* NO calibrated risk level.

### Normalization interpretations

I-1:
A name that is empty after normalization, including `''` or whitespace-only input such as NBSP-only, counts as empty.

I-2:
Whitespace handling follows Python `str.split()` semantics. The intended implementation is:

`" ".join(s.split())`

Unicode whitespace recognized by Python splitting is collapsed to one ASCII space and leading/trailing whitespace is trimmed.

I-3:
Exactly:

NFKC -> casefold -> collapse/trim

No second NFKC pass.

### Safety / interpretation

* the corpus is synthetic;
* the evaluation is not evidence of real-world AML/ER performance;
* a candidate link is for human review;
* a candidate link is never an identity determination.

### ER baseline measurement (v0.5)

* tier: `PROTOTYPE`
* evaluation-set version: `0.5`
* seed: `er_corpus_v0.5_freeze`
* rule_id: `exact_norm_name_exact_dob_v1`
* normalization_version: `v1`

**Measured confusion counts:**
* TP = 7
* FP = 1
* FN = 8
* TN = 17,189

**Universe:**
all unordered customer pairs

TN = every pair not contained in true_match_pairs and not predicted as a candidate link.

**Precision:**
```json
{
  "value": 0.875,
  "numerator": 7,
  "denominator": 8
}
```

**Recall:**
```json
{
  "value": 0.4666666666666667,
  "numerator": 7,
  "denominator": 15
}
```

**Recall by Scope:**
```json
{
  "within_adr_v1_scope": {
    "n_pairs": 7,
    "n_found": 7,
    "recall": 1.0,
    "numerator": 7,
    "denominator": 7
  },
  "outside_adr_v1_scope": {
    "n_pairs": 8,
    "n_found": 0,
    "recall": 0.0,
    "numerator": 0,
    "denominator": 8
  }
}
```

**Recall stratification:**

A pair can carry more than one transform label; the case_variant+whitespace_variant pair is counted under both labels, so per-transform denominators sum to 16 while the positive pairs total 15. Scope-level recall counts each pair once (7/7 within scope, 0/8 outside).

### Within ADR v1 scope

* case_variant: 3/3
* whitespace_variant: 3/3
* nfkc_variant: 1/1
* casefold_variant: 1/1

### Outside ADR v1 scope

Each is 0/1:

* dob_null: 0/1
* name_null: 0/1
* punctuation_variant: 0/1
* token_reorder_variant: 0/1
* typo_variant: 0/1
* abbreviation_variant: 0/1
* nickname_variant: 0/1
* diacritic_variant: 0/1

**FN Summary:**
* within-v1-scope unexpected FN = 0
* outside-v1-scope expected FN = 8

**FP analysis:**
* designed C3 homonym = 1
* unplanned FP = 0

**Abstention:**
* dob_null = 6
* name_empty_after_normalization = 2
* name_null = 1

**Reproduction Command:**
```bash
export $(cat .env | xargs) && PYTHONPATH=$(pwd)/src .venv/bin/python -m meridian.fixtures.er_baseline
```
Note: The v0.5 corpus with seed `er_corpus_v0.5_freeze` must already be loaded; loading the fixture is a SETUP database write; the baseline measurement itself is read-only.

**Limitations:**
* synthetic literal name pool
* outside-scope true identities are expected FN/abstentions, not rule defects
* the homonym pair is a deliberately designed known-false-positive class
* no transliteration coverage
* no phonetic matching coverage
* structural fidelity only
* no real-world ER performance claim
* candidate link is not an identity determination
* accuracy is not a headline metric

### Sanctions Candidate-Generation Fidelity Baseline (PROTOTYPE, synthetic)

#### Protocol & Identity
* Protocol identifier: `synthetic_candidate_generation_fidelity_v1`
* Tier: `PROTOTYPE`
* Matching rule ID: `exact_norm_name_v1`
* Normalization version: `v1`
* Watchlist name: `meridian_synthetic_watchlist`
* Watchlist version: `v1`
* Evaluation corpus: `meridian.fixtures.sanctions_eval_corpus`
* Frozen protocol: Evaluation cases, review pairs, candidate review table, and expected counts were frozen prior to baseline measurement (corpus and review table committed in `9fb9c32`; baseline fixture committed in `af74e92`).

#### Pair Semantics & Evaluation Universe
The evaluation universe comprises the full Cartesian product of the 8 frozen evaluation cases and the 5 synthetic watchlist subjects, yielding exactly 40 review pairs:
* Positive ground truth: 4 pairs
* Negative ground truth: 36 pairs
* Expected candidate pairs: 4 pairs
* Measured candidate pairs: 4 pairs

The matcher (`match_customer_against_watchlist`) is invoked once per evaluation case (8 invocations) against the synthetic watchlist entries. Each of that case's 5 subject pairs is then classified by comparing whether the subject appears in the returned candidate set against the hand-declared review record.

#### Evaluation Case Inventory & Review Mapping
* **CASE-SYNTH-001** (`IN_SCOPE_PRIMARY_POSITIVE`): Customer `"Aurelius Vance"`, DOB `1980-05-15`, planted `SUBJ-SYNTH-001`, expected candidates `{"SUBJ-SYNTH-001"}`, outcome `CANDIDATE_MATCHES_FOUND`. (5 pairs: TP=1 on `SUBJ-SYNTH-001`, TN=4).
* **CASE-SYNTH-002** (`IN_SCOPE_ALIAS_POSITIVE`): Customer `"  kaz   drake  "`, DOB `1992-08-04`, planted `SUBJ-SYNTH-004`, expected candidates `{"SUBJ-SYNTH-004"}`, outcome `CANDIDATE_MATCHES_FOUND`. Exact alias match after whitespace collapse and case-folding. (5 pairs: TP=1 on `SUBJ-SYNTH-004`, TN=4).
* **CASE-SYNTH-003** (`HOMONYM_POSITIVE_AND_FALSE_POSITIVE`): Customer `"Elena Rostova"`, DOB `1985-03-20`, planted `SUBJ-SYNTH-002`, expected candidates `{"SUBJ-SYNTH-002", "SUBJ-SYNTH-003"}`, outcome `CANDIDATE_MATCHES_FOUND`. Designed homonym where `SUBJ-SYNTH-002` (DOB 1985-03-20) is the planted target and `SUBJ-SYNTH-003` (DOB 1972-11-10) is a distinct entity sharing the primary listed name. (5 pairs: TP=1 on planted `SUBJ-SYNTH-002`, FP=1 on homonym `SUBJ-SYNTH-003`, TN=3).
* **CASE-SYNTH-004** (`UNRELATED_NEGATIVE`): Customer `"Zephyr Nightingale"`, DOB `1990-01-01`, planted `None`, expected candidates `set()`, outcome `NO_CANDIDATE_MATCH`. (5 pairs: TN=5).
* **CASE-SYNTH-005** (`DOB_ONLY_OVERLAP_NEGATIVE`): Customer `"Marcus Thorne"`, DOB `1980-05-15`, planted `None`, expected candidates `set()`, outcome `NO_CANDIDATE_MATCH`. Shares DOB with `SUBJ-SYNTH-001`, verifying DOB attribute never generates candidates when names differ. (5 pairs: TN=5).
* **CASE-SYNTH-006** (`PLANTED_POSITIVE_ABSTENTION_OUTSIDE_MATCHER_SCOPE`): Customer `None`, DOB `1980-05-15`, planted `SUBJ-SYNTH-001`, expected candidates `set()`, outcome `NOT_PERFORMED` (`CUSTOMER_NAME_MISSING`). Controlled abstention suppresses candidate generation while retaining positive ground truth. (5 pairs: FN=1 on planted `SUBJ-SYNTH-001`, TN=4).
* **CASE-SYNTH-007** (`ABSTENTION_EMPTY_AFTER_NORMALIZATION_NEGATIVE`): Customer `"\u00a0\u00a0"` (non-breaking spaces), DOB `None`, planted `None`, expected candidates `set()`, outcome `NOT_PERFORMED` (`CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION`). (5 pairs: TN=5).
* **CASE-SYNTH-008** (`EXCLUDED_TYPO_NEAR_MISS_NEGATIVE`): Customer `"Aurelius Vancx"`, DOB `1980-05-15`, planted `None`, expected candidates `set()`, outcome `NO_CANDIDATE_MATCH`. Typographical variant excluded by exact matching rule. (5 pairs: TN=5).

#### Stratification Breakdown (Recomputed from Frozen Review Table)
Stratification across all 8 case categories confirms the exact distribution of the 40 review pairs:
* **In-Scope Primary Positive** (5 pairs): TP=1, FP=0, FN=0, TN=4 (`CASE-SYNTH-001`)
* **In-Scope Alias Positive** (5 pairs): TP=1, FP=0, FN=0, TN=4 (`CASE-SYNTH-002`)
* **Homonym Positive & False Positive** (5 pairs): TP=1, FP=1, FN=0, TN=3 (`CASE-SYNTH-003`)
* **Unrelated Negative Control** (5 pairs): TP=0, FP=0, FN=0, TN=5 (`CASE-SYNTH-004`)
* **DOB-Only Overlap Negative Control** (5 pairs): TP=0, FP=0, FN=0, TN=5 (`CASE-SYNTH-005`)
* **Planted Positive Abstention (Missing Name)** (5 pairs): TP=0, FP=0, FN=1, TN=4 (`CASE-SYNTH-006`)
* **Negative Abstention (Empty Post-Normalization)** (5 pairs): TP=0, FP=0, FN=0, TN=5 (`CASE-SYNTH-007`)
* **Excluded Typo Near-Miss Negative** (5 pairs): TP=0, FP=0, FN=0, TN=5 (`CASE-SYNTH-008`)
* **Aggregate Totals** (40 pairs): TP=3, FP=1, FN=1, TN=35

#### Confusion Accounting & Abstentions
* True Positives (TP = 3):
  * `(CASE-SYNTH-001, SUBJ-SYNTH-001)`: Exact primary name match ("Aurelius Vance").
  * `(CASE-SYNTH-002, SUBJ-SYNTH-004)`: Exact alias match ("Kaz Drake").
  * `(CASE-SYNTH-003, SUBJ-SYNTH-002)`: Primary name match ("Elena Rostova" planted target).
* False Positives (FP = 1):
  * `(CASE-SYNTH-003, SUBJ-SYNTH-003)`: Designed homonym sharing listed primary name "Elena Rostova" but with divergent non-matching date of birth (1972-11-10 vs 1985-03-20); correctly generated as a candidate at the name-screening stage.
* False Negatives (FN = 1):
  * `(CASE-SYNTH-006, SUBJ-SYNTH-001)`: Missing customer name triggers controlled abstention (`NOT_PERFORMED`, `CUSTOMER_NAME_MISSING`), generating zero candidates while retaining planted positive ground truth.
* True Negatives (TN = 35): Non-matching names across negative test cases, non-breaking whitespace customer name abstention (`CASE-SYNTH-007`, `CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION`), and typo near-miss (`CASE-SYNTH-008`).

#### In-Scope vs Out-of-Scope Variants
* In-scope: Exact normalized-name equality under rule `exact_norm_name_v1` and normalizer `v1` (NFKC, casefold, whitespace collapse).
* Out-of-scope: Typographical variants (`CASE-SYNTH-008` "Aurelius Vancx"), phonetic matches, nicknames, transliterations, and reordered tokens are expected misses under the narrow rule, not defects.

#### Disclaimers & Not Claimable
* The evaluation measures synthetic candidate generation fidelity only.
* Candidates are generated exclusively for human review and must never be represented as an identity confirmation or sanctions determination.
* Exact matching can be trivially evaded by simple typographical or structural variants.
* NOT CLAIMABLE:
  * Real-world screening effectiveness
  * Regulatory screening compliance
  * Production detection performance
  * ROC-AUC
  * Thresholds, calibration, risk levels, or aggregate scores

#### Reproduction Command
```bash
PYTHONPATH=src uv run python -m meridian.fixtures.sanctions_baseline
```
Output SHA-256: `30ddd37022b7c5990a31e25bea0148d5ea26068d1ca5736d35178052081b537b` (15,730 bytes).
The command screens the in-memory synthetic corpus (`get_synthetic_watchlist_corpus()`). It does not read `watchlist_entries` from a database, so the database reader path is not exercised by this reproduction.

#### Complete Baseline Output (Verbatim)
```json
{
  "baseline_protocol": "synthetic_candidate_generation_fidelity_v1",
  "expected_candidates": 4,
  "fidelity_confusion_matrix": {
    "false_negatives": 1,
    "false_positives": 1,
    "true_negatives": 35,
    "true_positives": 3
  },
  "frozen_counts_match": true,
  "ground_truth_negatives": 36,
  "ground_truth_positives": 4,
  "matching_rule_id": "exact_norm_name_v1",
  "measured_candidates": 4,
  "mismatches": [],
  "normalization_version": "v1",
  "per_case_results": [
    {
      "case_id": "CASE-SYNTH-001",
      "case_matches_expected": true,
      "case_type": "IN_SCOPE_PRIMARY_POSITIVE",
      "customer_dob": "1980-05-15",
      "customer_name": "Aurelius Vance",
      "expected_candidate_subject_keys": [
        "SUBJ-SYNTH-001"
      ],
      "measured_candidate_subject_keys": [
        "SUBJ-SYNTH-001"
      ],
      "outcome": "CANDIDATE_MATCHES_FOUND",
      "per_subject_pairs": [
        {
          "equality_decision": "EQUAL",
          "expected_candidate": true,
          "fidelity_classification": "TRUE_POSITIVE",
          "ground_truth": "POSITIVE",
          "measured_candidate": true,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": "SUBJ-SYNTH-001",
      "reason_code": null
    },
    {
      "case_id": "CASE-SYNTH-002",
      "case_matches_expected": true,
      "case_type": "IN_SCOPE_ALIAS_POSITIVE",
      "customer_dob": "1992-08-04",
      "customer_name": "  kaz   drake  ",
      "expected_candidate_subject_keys": [
        "SUBJ-SYNTH-004"
      ],
      "measured_candidate_subject_keys": [
        "SUBJ-SYNTH-004"
      ],
      "outcome": "CANDIDATE_MATCHES_FOUND",
      "per_subject_pairs": [
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "EQUAL",
          "expected_candidate": true,
          "fidelity_classification": "TRUE_POSITIVE",
          "ground_truth": "POSITIVE",
          "measured_candidate": true,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": "SUBJ-SYNTH-004",
      "reason_code": null
    },
    {
      "case_id": "CASE-SYNTH-003",
      "case_matches_expected": true,
      "case_type": "HOMONYM_POSITIVE_AND_FALSE_POSITIVE",
      "customer_dob": "1985-03-20",
      "customer_name": "Elena Rostova",
      "expected_candidate_subject_keys": [
        "SUBJ-SYNTH-002",
        "SUBJ-SYNTH-003"
      ],
      "measured_candidate_subject_keys": [
        "SUBJ-SYNTH-002",
        "SUBJ-SYNTH-003"
      ],
      "outcome": "CANDIDATE_MATCHES_FOUND",
      "per_subject_pairs": [
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "EQUAL",
          "expected_candidate": true,
          "fidelity_classification": "TRUE_POSITIVE",
          "ground_truth": "POSITIVE",
          "measured_candidate": true,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "EQUAL",
          "expected_candidate": true,
          "fidelity_classification": "FALSE_POSITIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": true,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": "SUBJ-SYNTH-002",
      "reason_code": null
    },
    {
      "case_id": "CASE-SYNTH-004",
      "case_matches_expected": true,
      "case_type": "UNRELATED_NEGATIVE",
      "customer_dob": "1990-01-01",
      "customer_name": "Zephyr Nightingale",
      "expected_candidate_subject_keys": [],
      "measured_candidate_subject_keys": [],
      "outcome": "NO_CANDIDATE_MATCH",
      "per_subject_pairs": [
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": null,
      "reason_code": null
    },
    {
      "case_id": "CASE-SYNTH-005",
      "case_matches_expected": true,
      "case_type": "DOB_ONLY_OVERLAP_NEGATIVE",
      "customer_dob": "1980-05-15",
      "customer_name": "Marcus Thorne",
      "expected_candidate_subject_keys": [],
      "measured_candidate_subject_keys": [],
      "outcome": "NO_CANDIDATE_MATCH",
      "per_subject_pairs": [
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": null,
      "reason_code": null
    },
    {
      "case_id": "CASE-SYNTH-006",
      "case_matches_expected": true,
      "case_type": "PLANTED_POSITIVE_ABSTENTION_OUTSIDE_MATCHER_SCOPE",
      "customer_dob": "1980-05-15",
      "customer_name": null,
      "expected_candidate_subject_keys": [],
      "measured_candidate_subject_keys": [],
      "outcome": "NOT_PERFORMED",
      "per_subject_pairs": [
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "FALSE_NEGATIVE",
          "ground_truth": "POSITIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": "SUBJ-SYNTH-001",
      "reason_code": "CUSTOMER_NAME_MISSING"
    },
    {
      "case_id": "CASE-SYNTH-007",
      "case_matches_expected": true,
      "case_type": "ABSTENTION_EMPTY_AFTER_NORMALIZATION_NEGATIVE",
      "customer_dob": null,
      "customer_name": "\u00a0\u00a0",
      "expected_candidate_subject_keys": [],
      "measured_candidate_subject_keys": [],
      "outcome": "NOT_PERFORMED",
      "per_subject_pairs": [
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NO_CANDIDATE_ABSTENTION",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": null,
      "reason_code": "CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION"
    },
    {
      "case_id": "CASE-SYNTH-008",
      "case_matches_expected": true,
      "case_type": "EXCLUDED_TYPO_NEAR_MISS_NEGATIVE",
      "customer_dob": "1980-05-15",
      "customer_name": "Aurelius Vancx",
      "expected_candidate_subject_keys": [],
      "measured_candidate_subject_keys": [],
      "outcome": "NO_CANDIDATE_MATCH",
      "per_subject_pairs": [
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-001"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-002"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-003"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-004"
        },
        {
          "equality_decision": "NOT_EQUAL",
          "expected_candidate": false,
          "fidelity_classification": "TRUE_NEGATIVE",
          "ground_truth": "NEGATIVE",
          "measured_candidate": false,
          "subject_key": "SUBJ-SYNTH-005"
        }
      ],
      "planted_subject_key": null,
      "reason_code": null
    }
  ],
  "total_evaluation_cases": 8,
  "total_review_pairs": 40,
  "total_subjects": 5,
  "watchlist_name": "meridian_synthetic_watchlist",
  "watchlist_version": "v1"
}
```

---

## 6. Agent Evaluation

**Metrics:** task success rate, correct tool selection rate, invalid tool-call rate, investigation completeness, unsupported-claim rate, hallucination rate, cost/latency per investigation.

**Method:** run the full fixture set (§7) through the orchestrator end-to-end; for each run, check: did the right agents get dispatched, did tool calls succeed/validate, did any finding lack supporting evidence (unsupported-claim rate — this should be **zero** given the evidence-sufficiency gate; if it isn't, that's a defect, not a metric to accept), did the reasoning chain (Fact→Signal→Interpretation→Recommendation) stay intact.

---

## 7. System Evaluation

**Metrics:** reliability (successful-completion rate across the fixture set), latency (per investigation, per agent), throughput (investigations/hour under test load), failure recovery (does the system correctly reach `INCOMPLETE_INSUFFICIENT_EVIDENCE` / `FAILED` states rather than silently corrupting state), reproducibility (does re-running the same alert against the same data/model version produce materially the same findings).

---

## 8. Human Evaluation

**Metrics:** analyst agreement (does a human reviewer agree with the AI's risk level and recommendation), evidence completeness (does the report surface everything a human would have found manually), report correctness, investigation-time reduction, usability.

**Method:** compare AI-generated investigations against a small set of hand-written reference investigations on the same synthetic fixture cases (produced by the project author role-playing an analyst, or a domain-knowledgeable reviewer, clearly labeled as such). Investigation-time-reduction claims (e.g., "reduced investigation time by X%") may only be published if actually measured on a real timed comparison — never estimated. This directly enforces `PROJECT_BRIEF` §29's own caution against inventing improvement numbers.

---

## 9. Synthetic Fixture Set

The `v0.1`, `v0.2`, and `v0.3` synthetic fixture corpora (`src/meridian/fixtures/generator.py`) produce deterministic evaluation sets.
- **v0.1:** 20 explicitly labeled scenarios, used to verify code paths. Very rigid numeric values with no variance.
- **v0.2:** 58 explicitly labeled scenarios, introducing **seeded variance** and **hard negative subtypes**.
  - **Scenario taxonomy:** structuring, rapid movement, circular transfers, mule chains, clean control (subtypes: typical, large_legitimate), and insufficient history.
  - **Subtypes and Variance:** In v0.2, scenarios are subdivided into *baseline* (typical suspicious behavior) and *elevated* (highly suspicious behavior). Clean controls include *typical* and *large_legitimate* (hard negatives with amounts resembling suspicious activity but clean topology). All generated amounts, timestamps, and UUIDs are deterministically derived from the combination of the `seed` and `fixture_id` via SHA-256 hashes, producing reproducible distributions with within-class variance rather than identical duplicate values.
- **v0.3:** 58 explicitly labeled scenarios matching v0.2's composition (8 of each class + 2 specials). Introduces beneficiary-state quotas (20% absent, 40% fresh, 40% established) applied via a common distribution independent of scenario class. Also introduces exact target-velocity generation via isolated extra transaction counts, and strictly neutral vocabulary (`large_transaction`, `new_beneficiary`, `rapid_movement`) for alert types decoupled from ground truth. Like v0.1/v0.2, v0.3 is a synthetic evaluation fixture corpus and makes no statistical independence or real-world predictive performance claim.
- **v0.4:** Adds structural graph ground truth and 96 uniform transaction-derived `TRANSACTED_WITH` relationships alongside the 3 inherited hand-authored worked-example `TRANSACTED_WITH` relationships, yielding 99 total `TRANSACTED_WITH` relationships.
  - v0.1 contained planted `TRANSACTED_WITH` relationships.
  - v0.2/v0.3 do not contain a general transaction-to-relationship derivation rule.
  - v0.3 nevertheless contains inherited hand-authored worked-example `TRANSACTED_WITH` relationships.
  - v0.4 defines the first uniform transaction-derived augmentation rule.
  - v0.4 ground truth is generator-defined structural ground truth.
  - This task makes no performance claim. Task 10 is not measured by this task, and no community-detection or centrality evaluation is introduced.
- **v0.5:** Adds the ER Evaluation Corpus. It appends exactly 37 new customers (15 true match pairs across 13 true groups, and 5 negative categories) designed strictly to evaluate ER structural fidelity and adherence to ADR-0006 v1 normalization boundaries. v0.5 is purely additive; it perfectly preserves byte-for-byte all prior rows, graph topology, and risk signals. It contains no ER logic itself.
- **Explicit ground truth:** Each fixture explicitly declares its intended ground truth (e.g. `AML_STRUCTURING`, `CLEAN`) and evaluation target directly in its manifest.
- **Planted pattern metadata:** The specific synthetic behavior injected into the data is tracked exactly, along with the IDs of pattern members.
- **Split / pattern atomicity:** Each fixture instance acts as a fully self-contained atomic scenario mapped strictly to either `train` or `eval` deterministically via a hash-based assignment. A single pattern's data never crosses the split boundary.
- **Limitations:** While v0.2 adds intra-class variance and hard negatives, it remains synthetic. The numeric distributions do not represent a calibrated true-to-life realistic simulation.

---

## 10. What Is Explicitly Disallowed

- Publishing a metric without stating its tier and evaluation-set version.
- Publishing a resume/portfolio claim (e.g., "reduced investigation time by 90%") without a real measured basis (`PROJECT_BRIEF` §29).
- Treating an LLM-as-judge score as ground truth without labeling it as an automated proxy metric.
- Skipping evaluation for a "prototype" feature and presenting it as evaluated anyway.

---

## 11. Related Documents

`docs/AI_SAFETY_AND_GUARDRAILS.md` §5 (confidence tiers used in reports), `docs/TESTING.md` (fixture reuse for regression), `docs/DATA_AND_DATASET_STRATEGY.md` (fixture generation), `docs/DECISIONS.md` (ADR needed if evaluation methodology changes materially).


## Phase B unified execution (2026-10-26, PROTOTYPE)

`evaluation/phase-b-unified.json` records actual execution of the v0.2 amount,
v0.3 transaction-signal, v0.4 graph, v0.5 entity-resolution and synthetic sanctions
baselines. It reuses the immutable paired policy result rather than running
HELDOUT again. Human comparison: **NOT PERFORMED**.

Run only against the marked disposable `meridian_test` database on loopback
port 55432, with the three role URLs documented in TESTING.md exported:

```bash
PYTHONPATH=src HF_HUB_OFFLINE=1 uv run --frozen --no-sync python -m meridian.evaluation.run --output /tmp/meridian-evaluation.json
```

The runner clears source fixtures in that disposable database, refuses downstream
alerts, and cleans its fixture data afterward. Existing output files are not
overwritten. Do not run it concurrently with database tests.

Measured limitations are material: v0.2 amount-deviation eval ROC-AUC is 0.479167
(4 positives, 12 negatives). ER precision is 7/8 and overall recall 7/15; the
seven cases within the exact-name/exact-DOB rule's scope were found. Sanctions
produced its expected four candidates, including a designed false positive and
one missed ground-truth positive; candidate matching is not a sanctions decision.
These are synthetic structural checks, not real-world AML effectiveness.

### Single locked policy comparison

Ankur accepted ADR-0009 and the fixed 0.620313 prototype cosine gate before the
paired HELDOUT run. The result and completion receipt are
`evaluation/policy_retrieval_eval_v1.heldout.json` and
`evaluation/policy_retrieval_eval_v1.heldout-receipt.json`.

| Cohort | Original RRF gate | Approved cosine gate |
|---|---|---|
| HELDOUT C3 assessed negatives (5) | Retrieved all 5 | Abstained on all 5 |
| HELDOUT C4 assessed positives (8) | Retrieved all 8 | Retrieved all 8 |
| C1 descriptive alert types (3) | Retrieved all 3 | Retrieved all 3 |

One C3 and three C4 HELDOUT queries are NOT_ASSESSED and excluded from abstention
accuracy claims. C4 strict Hit@1=0.875, MRR=0.9375, precision@5=0.525 and
recall@5=0.958333 are identical for both systems because ranking is unchanged.
C1 strict Hit@1 and MRR are 1.0; precision@5=0.533333 and recall@5=1.0.
C2 remains provisional and was not executed. Full per-query rankings and metrics
are retained in the artifacts. No threshold was tuned on HELDOUT.

The gate uses a tiny DEV sample (five assessed negatives, four positives), is
**not calibrated**, and does not establish policy applicability or citation
correctness. Query-level splits can share scenario families. Missing-coverage
queries marked NOT_ASSESSED remain a known limitation. Do not rerun the frozen
HELDOUT protocol or represent these labels as independently validated.
