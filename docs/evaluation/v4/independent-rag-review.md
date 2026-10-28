# Request for an independent, untouched RAG final set

Status: REVIEW PACKAGE PREPARED; queries/labels/reviewer approvals NOT PROVIDED.
Do not reuse the 48 v3 DEV questions as final validation after reviewing them.
Do not generate labels here and call them independent. Runtime stays BGE-small
with the existing gate; no model comparison or threshold tuning is requested.

Provide a reviewer with the two licensed local BIS PDFs and source manifest
`../v2/reference-sources.json`, the hashed 494-chunk corpus from v2, and the
rubrics below. Keep PDFs/chunks local under the recorded noncommercial terms.
Identify the reviewer, expertise, conflicts, date and actual review scope.
The reviewer should author a new set without seeing system rankings/scores;
a second reviewer should adjudicate disagreements where feasible. Record if
review is maintainer-only rather than independent subject-matter review.

Suggested minimum coverage: 20 distinct positive topic families and 20 negative
families, including both source documents, terminology variations, close but
wrong passages, missing internal policies, jurisdiction and version mismatches,
contradictions and out-of-domain requests. This is a coverage target, not a
statistical guarantee. Keep paraphrases in the same family and compare normalized
texts/topic families against v1/v2/v3 to flag exact or conceptual reuse. Exclude
DEV families where possible; document unavoidable topic overlap. Keep final
queries sealed from the implementation executor until configuration is locked.

## Annotation rubrics

- Passage grade 3: directly supports the requested proposition with appropriate
  qualifications. Grade 2: substantial but incomplete support; identify missing
  context. Grade 1: topical only. Grade 0: irrelevant, contradictory or wrong
  applicability. Record all reviewed supporting alternatives, not one convenient
  gold passage. Unjudged passages remain explicitly unjudged.
- Abstention: required if no corpus passage supports the requested proposition
  in the requested context. A request endorsing a false premise differs from a
  question that can be answered by correcting it; record the distinction.
- Applicability: record document ID, edition, page, jurisdiction, effective/current
  status and whether the request seeks international guidance, domestic law or
  an internal bank rule. International BIS guidance cannot establish a bank's
  internal policy or a current jurisdiction-specific statutory requirement.
- Citation: an existing ID/text hash is necessary but insufficient. Verify exact
  passage support and context; flag misleading omissions and source conflicts.

## Review record template

One JSON object per query, completed by the reviewer:
`id`, `family`, `query`, `expected_action` (RETRIEVE/ABSTAIN/UNRESOLVED),
`passages` (chunk_id, grade, support rationale, applicability), `negative_rationale`,
`source_constraints`, `reviewer`, `reviewed_at`, `adjudication`, `overlap_check`.
Keep UNRESOLVED examples out of headline metrics; report their count.

Before one final measurement, archive the signed review record, canonical query
hash, corpus hash, exact runtime/configuration hash, metric definitions and
explicit maintainer authorization. Do not fit a gate using final labels or tune
after final results. Any independent-validation claim must match the review
actually performed. Until this record exists, final validation remains PENDING.
