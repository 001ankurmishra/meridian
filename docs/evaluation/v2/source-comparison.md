# External source suitability and limits

Checked 2026-10-26/27. The selected financial archive is IBM **Dataset A,
February 2021**, not the 2023 HI-Small dataset. No additional large archive was
downloaded for this comparison.

| Aspect | Original February 2021 | Newer February 2023 release |
|---|---|---|
| Provenance | Publisher-linked IBM Box file 780504045395; locally downloaded and checksum-pinned | Publisher-linked Kaggle release; paper and IBM preprocessing code inspected; archive not acquired |
| Schema | Timestamp, separate bank/account endpoints, received/paid amounts and currencies, payment format, binary label; exact positional header verified | IBM preprocessing code consumes corresponding fields, including positional account columns 2 and 4 |
| Labels | Illicit-origin funds in IBM's synthetic world, including onward transfers; not human AML determinations | Same broad generator-label concept; exact archive-specific label distribution not locally verified |
| Versions | One January 2019 transaction period, ~45.4 million rows | HI/LI variants with small/medium/large sizes described in the paper |
| License | CDLA-Sharing-1.0 for data; repository Apache-2.0 is separate | Publisher identifies data as CDLA-Sharing-1.0; archive-specific notices must be checked on eventual acquisition |
| Suitability | Independent of Meridian's generators; useful for bounded account-level diagnostics. Null/signed amounts, one-month history and absent customer ownership limit native signal applicability | Better alignment with the published 2023 benchmark literature; does not itself solve absent ownership or real-world validity |
| Local quality status | Full validation evidence recorded separately | UNKNOWN: no local counts/checksum/missing-value audit; do not infer cleanliness from the paper |

Authoritative references:

- [IBM AML-Data README](https://github.com/IBM/AML-Data/tree/366436e605ac7713bf4eee8b4fbc45984d64427c), revision checked using the publisher's Git remote.
- [Original source and documentation](https://ibm.box.com/v/AML-Anti-Money-Laundering-Data).
- [IBM's 2023 research paper](https://papers.nips.cc/paper_files/paper/2023/file/5f38404edff6f3f642d6fa5892479c42-Paper-Datasets_and_Benchmarks.pdf).
- [IBM preprocessing implementation](https://github.com/IBM/Multi-GNN/blob/252b0252afca109d1d216c411c59ff70753b25fc/format_kaggle_files.py).
- [CDLA-Sharing-1.0](https://cdla.dev/sharing-1-0/).

The 2023 paper evaluates chronological partitions and several learned models.
Those published scores are not transferable to this older archive or Meridian's
untrained signals. It describes a range of synthetic laundering proportions and
sizes; synthetic completeness of generator labels does not establish regulatory
validity. Meridian neither implements nor downloads the paper's GNN stack here.

## Public reference provenance addendum

The frozen corpus manifest and text hashes are preserved. Subsequent checks of
the official landing pages confirm additional metadata; this addendum does not
silently rewrite approved corpus bytes:

- [2020 AML guidelines](https://www.bis.org/publications/202007-guidelines-sound-management-risks-related-money-laundering-and-financing-terrorism-revisions-supervisory-cooperation): dated 2 July 2020, explicitly marked **Current**. BIS describes voluntary jurisdictional implementation, not a universal binding bank policy.
- [2024 Core Principles](https://www.bis.org/publications/202404-standards-core-principles-effective-banking-supervision): dated 25 April 2024, marked **Consolidated**, incorporated into the Basel Framework and effective immediately as that standard. The frozen corpus conservatively has null `effective_date`; domestic enforceability remains unestablished.
- The AFS10 consolidated-guidelines web page explicitly identifies a draft under consultation. It was not ingested as adopted guidance.

The two PDFs remain copyrighted. The [BIS terms](https://www.bis.org/about/terms-conditions)
permit noncommercial use and bounded attributed excerpts. Full PDFs and extracted
chunks stay in ignored local storage for noncommercial research; no unrestricted
commercial redistribution license is claimed. Publication identity, copyright,
PDF page location and source/version metadata accompany each chunk. Covers and
copyright pages are excluded from retrieval. PDF page 4 in both files was rendered
and visually confirmed blank before its explicit exclusion. Text extraction can
retain typography artifacts; it is not a substitute for reading the cited PDF.

FATF and RBI corpus content remains deferred pending document-specific permission
and currency review. This is an international reference corpus, not a complete
Indian regulatory corpus or Meridian's internal procedures.
