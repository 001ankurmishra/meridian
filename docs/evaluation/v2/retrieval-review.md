# Retrieval v2 label review package

Canonical SHA256: `d6d9a3363545c0cd6c820a3ea2367155860e2152a4d9d06828d55b91e98d1c37`

Status: **AI-PROPOSED; NOT independently reviewed; NOT FROZEN**. No retrieval outcomes have been measured.

Corpus: two published BIS PDFs, 494 page-confined chunks. Full text stays in ignored local scratch for noncommercial research. This corpus contains public reference material, not Meridian bank policy.

The complete protocol, labels, rationales and split assignments are in `retrieval-review.json`. Source identities, permissions and versions are in `reference-sources.json`.

Review each relevant-passage set for completeness and applicability. Read the actual PDF page (page numbers are PDF positions, not printed pagination). Approving this package is maintainer review, not independent expert validation.

| ID | Split | Query | Expected chunk(s) / negative rationale |
|---|---|---|---|
| v2-monitoring-1 | DEV | According to paragraph 28 of the July 2020 BCBS AML guidelines, what must a bank do if it considers an IT monitoring system unnecessary? | bis-aml-2020:pdf-page-10:chunk-3 |
| v2-monitoring-2 | DEV | In the July 2020 BCBS guidance, how must a bank justify using an alternative to automated monitoring? | bis-aml-2020:pdf-page-10:chunk-3 |
| v2-alert_assessment-1 | DEV | Under paragraph 30 of the July 2020 BCBS AML guidance, who further assesses alerts of unusual transactions? | bis-aml-2020:pdf-page-11:chunk-1 |
| v2-alert_assessment-2 | DEV | What human assessment follows IT-generated unusual transaction alerts in the July 2020 BCBS guidelines? | bis-aml-2020:pdf-page-11:chunk-1 |
| v2-record_updates-1 | DEV | What does paragraph 54 of the July 2020 BCBS AML guidance say about keeping CDD records current? | bis-aml-2020:pdf-page-15:chunk-3 |
| v2-record_updates-2 | DEV | How does regularly updating CDD information assist monitoring according to the July 2020 BCBS guidance? | bis-aml-2020:pdf-page-15:chunk-3 |
| v2-retention-1 | HELDOUT | Under paragraph 52 of the July 2020 BCBS AML guidelines, how long should records be kept when an investigation continues after account closure? | bis-aml-2020:pdf-page-15:chunk-2 |
| v2-retention-2 | HELDOUT | According to the July 2020 BCBS recordkeeping guidance, may records be discarded during ongoing litigation after an account closes? | bis-aml-2020:pdf-page-15:chunk-2 |
| v2-confidentiality-1 | HELDOUT | What does paragraph 57 of the July 2020 BCBS AML guidance say about confidentiality and timeliness in suspicious activity reporting procedures? | bis-aml-2020:pdf-page-16:chunk-1 |
| v2-confidentiality-2 | HELDOUT | In the July 2020 BCBS guidelines, how should reporting procedures protect confidentiality while ensuring swift investigations? | bis-aml-2020:pdf-page-16:chunk-1 |
| v2-correspondent-1 | HELDOUT | According to principle 29 criterion 6 in the April 2024 Basel Core Principles, what should banks learn about a respondent bank? | bis-core-2024:pdf-page-71:chunk-1 |
| v2-correspondent-2 | HELDOUT | What correspondent-banking due diligence information does criterion 6 of principle 29 in the April 2024 Basel Core Principles call for? | bis-core-2024:pdf-page-71:chunk-1 |
| v2-recipe | DEV | How do I bake a sourdough loaf? | No cooking corpus. |
| v2-rupee_threshold | DEV | What exact INR amount requires Meridian Bank to automatically freeze an account? | No Meridian internal policy or automatic-freeze authority; public guidance cannot supply a bank-specific threshold. |
| v2-capital_aml | DEV | Does meeting Basel capital adequacy ratios prove that a customer transaction is legitimate? | Capital standards do not establish legitimacy of an individual transaction. |
| v2-stock | DEV | Which stock will double in price tomorrow? | No investment forecasting evidence. |
| v2-rbi_current | HELDOUT | What is the exact current RBI deadline in hours for this bank to file an Indian suspicious transaction report? | No current RBI source or domestic applicability evidence in corpus. |
| v2-old_source | HELDOUT | Quote the original September 2012 Basel Core Principles criterion 29(5)(f) verbatim from the 2012 source. | 2012 text is not ingested; a later citation or similar rule is not the original source. |
| v2-draft_binding | HELDOUT | Has the January 2026 draft consolidated AFS10 guidance become binding Indian law? | Draft is not ingested or verified as adopted; international guidance is not domestic law. |
| v2-ten_year | HELDOUT | Where do the July 2020 BCBS guidelines mandate destruction of all records exactly ten years after account closure even during litigation? | Premise conflicts with the cited continued-retention guidance; no supporting passage. |

Existing BGE + PostgreSQL hybrid ordering and ADR-0009 threshold remain unchanged. The new corpus may expose gate failures; those will be reported, not tuned away. Labels are binary, so nDCG uses binary gains. Abstention means no returned chunks after the existing gate. Label-level source applicability and mechanical citation validity are separate metrics.

Limitations: only two international sources, six positive topic families, no reviewed RBI/FATF content, no human comparison, no generated answers, no proven domestic applicability. The unapproved 2026 BIS draft is explicitly excluded.
