# ADR-0009: Prototype absolute similarity gate for policy retrieval

Status: ACCEPTED by Ankur, explicit Codex chat approval on 2026-10-26 (Asia/Kolkata).
Prepared: 2026-10-26 (Asia/Kolkata), before any HELDOUT retrieval measurement.

## Concrete decision

Enable a query-level minimum cosine similarity of **0.620313** between the
prefixed query embedding and any chunk in the complete policy corpus. Below
that threshold, return the existing `PolicyEvidenceInsufficient` abstention.
At or above it, preserve the existing lexical/semantic RRF ranking, top-five
selection and RRF threshold 0.01. Empty/missing/non-finite maximum similarity
abstains. The immutable bge model/tokenizer revision and CPU inference remain.
No state-machine or schema change is needed.

Implementation is available through the optional `absolute_similarity_threshold`
argument of `retrieve_policy_evidence`; its production default is now 0.620313; explicit None selects the original baseline.

## Evidence and threshold selection

`docs/evaluation/policy_retrieval_eval_v1.dev.json` contains the first DEV result
against the approved frozen corpus and labels. All five SHOULD_ABSTAIN negatives
were retrieved by the original RRF gate. Their maximum cosine similarities are
0.400545–0.511135. Four SHOULD_RETRIEVE positives have maxima 0.729491–0.783073.
The proposed threshold is the midpoint between the largest labeled negative
and smallest labeled positive, rounded to six decimals. The five NOT_ASSESSED
queries were excluded from threshold selection. No HELDOUT score, label outcome
or retrieval result informed the threshold.

## Limits and alternatives

This is a PROTOTYPE threshold fitted to nine labeled DEV examples, not calibrated
or independently validated. The margin may not generalize. Some in-domain
coverage-gap queries have high similarity; this gate cannot establish whether a
specific applicable policy exists. A passing gate does not validate every cited
chunk. RRF retains its original ranking and limitations.

Keeping only RRF 0.01 cannot reject top semantic matches: even rank one without
lexical support scores 1/61 > 0.01. A learned classifier, reranker or additional
model would expand the approved scope and is unnecessary for this experiment.

## Locked validation proposed before HELDOUT

The maintainer accepted this ADR before any HELDOUT measurement. Lock one paired HELDOUT run comparing the
original RRF gate and the fixed 0.620313 query gate, with the same rankings and
existing frozen metric/abstention definitions. Report cohorts separately, exclude
NOT_ASSESSED from decision counts, and report C1 descriptively. Keep C2 excluded
until the legacy workflow is confirmed. Do not tune after HELDOUT. If the result
is poor, report it; any later threshold requires a new evaluation protocol.
Human-comparison results remain NOT PERFORMED.
