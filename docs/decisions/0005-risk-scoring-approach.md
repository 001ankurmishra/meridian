# ADR-0005: Risk-Scoring Approach (Phase 2)

Status: Proposed
Date: 2026-10-03

## Context

- FACT: F10 (`docs/FEATURES.md`) describes MVP risk scoring as PROTOTYPE tier, to be replaced in Phase 2 by an experimentally validated model; F14 describes training/validation against labeled synthetic patterns "where applicable". `docs/ROADMAP.md` lists "Calibrated risk scoring (replacing prototype weights) with documented methodology and evaluation" in Phase 2 scope.
- FACT: The current risk engine (`src/meridian/risk_engine/risk_signals.py`) passes the amount-deviation multiple through as the score value, with weight 1.0 and methodology PROTOTYPE.
- FACT: Two further deterministic signals (transaction velocity, beneficiary age) are implemented as computation-only and are not wired into dispatch, F10, evidence or reports.
- FACT: The evaluation corpora (v0.1 to v0.3) are produced by Meridian's own generators. `docs/EVALUATION.md` records single-signal measurements on corpus v0.3 (see the section "Single-Signal Baselines on Corpus v0.3"). The three signals behave very differently there, including pooled AUC values below 0.5 for velocity and beneficiary age; those values follow from fixture-design parameters (typology-defined velocity, class-independent beneficiary state) and not from detection behaviour. The evaluable set is small (see n per split in EVALUATION.md).
- FACT: `docs/DECISIONS.md` anticipates a risk-scoring ADR around Phase 2 calibration work.
- Consequence: weights or thresholds fitted to these corpora would encode generation parameters, which `CLAUDE.md` §10 and `docs/EVALUATION.md` §9 prohibit presenting as validated.

## Decision (Proposed)

D1. Meridian does not present an aggregate numeric risk score or risk level derived from parameters fitted to the v0.x synthetic corpora. F10 continues to surface per-signal derived values,
    labelled PROTOTYPE. This describes the current behaviour and changes no code.

D2. A composite score, fitted weights, or calibrated thresholds may be introduced only when all of these gates hold:
    - G1: evaluation data whose label-signal relationships are not defined by Meridian's own generators, for example an externally sourced labeled dataset (EXTERNAL: license and provenance must
      be verified per `docs/DATA_AND_DATASET_STRATEGY.md` §2) or another independently specified source.
    - G2: a sample-size and uncertainty requirement, stating the target standard error and the resulting minimum evaluable units per split, recorded in an amendment to this ADR before any fitting.
    - G3: a fixed train/evaluation split, with no tuning on the evaluation split.
    - G4: signal directions and features fixed before measurement.
    - G5: Unknown signal values are never imputed.
    - G6: all scoring is deterministic computation; no LLM is used for numerical risk calculation.
    - G7: results stay PROTOTYPE until G1 to G6 hold; after that, EXPERIMENTALLY_CALIBRATED applies to that dataset and version only (`docs/EVALUATION.md` §1).

D3. Bands or labels (for example LOW/MEDIUM/HIGH) are Interpretation, not signals. They require a documented rule and a tier label, must never be shown without the underlying signal values and
    evidence links, and must not state or imply an AML conclusion. The Observed Fact -> Derived Signal -> Interpretation -> Recommendation chain is preserved.

D4. OPEN (maintainer decision; not decided by this ADR): the Phase 2 bullet "Calibrated risk scoring" cannot reach EXPERIMENTALLY_CALIBRATED on the current synthetic corpora. The maintainer
    chooses between (a) re-scoping the bullet to "documented methodology plus measured per-signal evaluation (PROTOTYPE)", with composite calibration gated on G1; or (b) pursuing G1 now by
    evaluating an externally sourced labeled dataset.

## Alternatives Considered

- Fit a composite model (for example logistic regression) on corpus v0.3: rejected. The evaluable set is small and the signal-label relationships are generator-defined, so the fit would encode
  generation parameters.
- Hand-set weights and thresholds as the final method: rejected as final (arbitrary weights, `CLAUDE.md` §10); acceptable only as clearly labelled PROTOTYPE.
- Calibrate amount_deviation alone: superseded by the Phase 2 kickoff resolution (bounded option B: add documented deterministic signals, then calibrate the named signal set).
- Add noise or realism to the fixtures until a fitted composite looks meaningful: rejected as the primary route; noise processes designed by the same author remain generator-defined. It may still
  serve plumbing and regression tests.

## Consequences

- Claims stay honest: no composite or calibrated score is presented on synthetic-only evidence, and F10 stays simple.
- The Phase 2 "calibrated risk scoring" deliverable is not satisfiable as written until G1 is met; the D4 decision is required.
- Foreclosed: presenting a composite score or calibrated thresholds on synthetic-only evidence.
- Independent follow-ups, not part of this ADR: wiring the existing signals into evidence and reports per F3; the D4 decision; if D4(b), a separate dataset-evaluation task with EXTERNAL verification.

## PROHIBITED
- Any change to src/**, tests/**, alembic/**, ui/**, pyproject.toml, uv.lock, .github/**, docker/**, and any doc other than the three listed. No ADR other than 0005.
- Changing docs/EVALUATION.md, docs/FEATURES.md, docs/ARCHITECTURE.md or docs/DATABASE_SCHEMA.md.
- Marking the ADR Accepted, deciding D4, adding numbers not present in the repository, or adding any implementation plan beyond the follow-ups already listed.
- Fixing unrelated issues (list them in the report instead).
