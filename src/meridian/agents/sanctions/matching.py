"""
Exact normalized-name candidate matching for F11 sanctions screening.

Implements rule exact_norm_name_v1 per ADR-0008 D2, D3, D4, and D8:
- Exact normalized-name equality between customer name and watchlist listed names.
- Candidates generated per subject_key, listing all matched entries.
- DOB is compared only as an attribute (EQUAL, DIFFERENT, NOT_COMPARABLE).
- Controlled abstention (NOT_PERFORMED) for an unavailable watchlist version,
  a missing customer name, or an empty normalized name. This module is the
  single place where all controlled abstention is produced.
"""

import datetime
from collections import defaultdict

from meridian.agents.sanctions.normalization import (
    NORMALIZATION_VERSION,
    normalize_full_name,
)
from meridian.agents.sanctions.types import (
    MATCHING_RULE_ID,
    AbstentionReason,
    DobComparison,
    LoadedWatchlistVersion,
    NameType,
    SanctionsCandidate,
    SanctionsMatchResult,
    ScreeningOutcome,
    WatchlistEntry,
    WatchlistReadResult,
    WatchlistVersionNotLoaded,
)


def compare_dob(
    customer_dob: datetime.date | None,
    subject_dob: datetime.date | None,
) -> DobComparison:
    """
    Compares customer DOB and watchlist subject DOB.

    Returns:
        EQUAL if both are non-null and identical.
        DIFFERENT if both are non-null and differ.
        NOT_COMPARABLE if either side is None.
    """
    if customer_dob is None or subject_dob is None:
        return DobComparison.NOT_COMPARABLE
    if customer_dob == subject_dob:
        return DobComparison.EQUAL
    return DobComparison.DIFFERENT


def match_customer_against_watchlist(
    customer_name: str | None,
    customer_dob: datetime.date | None,
    watchlist: WatchlistReadResult,
) -> SanctionsMatchResult:
    """
    Screens a customer against a typed watchlist read result.

    Args:
        customer_name: Verbatim customer full name literal (nullable).
        customer_dob: Customer date of birth (nullable).
        watchlist: LoadedWatchlistVersion to screen against, or
            WatchlistVersionNotLoaded if the pinned version has no rows.

    Returns:
        SanctionsMatchResult with deterministic outcome, candidates, and metadata.
        A WatchlistVersionNotLoaded input can only yield
        NOT_PERFORMED(WATCHLIST_VERSION_NOT_LOADED); it takes precedence over
        customer-name abstentions.

    Raises:
        TypeError: If watchlist is neither accepted type (for example the
            former tuple-of-entries input). The message never echoes the input.
    """
    if isinstance(watchlist, WatchlistVersionNotLoaded):
        return SanctionsMatchResult(
            outcome=ScreeningOutcome.NOT_PERFORMED,
            reason_code=AbstentionReason.WATCHLIST_VERSION_NOT_LOADED,
            candidates=(),
            watchlist_name=watchlist.watchlist_name,
            watchlist_version=watchlist.watchlist_version,
            matching_rule_id=MATCHING_RULE_ID,
            normalization_version=NORMALIZATION_VERSION,
        )
    if not isinstance(watchlist, LoadedWatchlistVersion):
        raise TypeError(
            "watchlist must be a LoadedWatchlistVersion or WatchlistVersionNotLoaded."
        )

    w_name = watchlist.watchlist_name
    w_ver = watchlist.watchlist_version
    watchlist_entries = watchlist.entries

    # 1. Controlled Abstention Checks (ADR-0008 D8)
    if customer_name is None:
        return SanctionsMatchResult(
            outcome=ScreeningOutcome.NOT_PERFORMED,
            reason_code=AbstentionReason.CUSTOMER_NAME_MISSING,
            candidates=(),
            watchlist_name=w_name,
            watchlist_version=w_ver,
            matching_rule_id=MATCHING_RULE_ID,
            normalization_version=NORMALIZATION_VERSION,
        )

    norm_customer = normalize_full_name(customer_name)
    if not norm_customer:
        return SanctionsMatchResult(
            outcome=ScreeningOutcome.NOT_PERFORMED,
            reason_code=AbstentionReason.CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION,
            candidates=(),
            watchlist_name=w_name,
            watchlist_version=w_ver,
            matching_rule_id=MATCHING_RULE_ID,
            normalization_version=NORMALIZATION_VERSION,
        )

    # 2. Group entries by subject_key
    subject_entries: dict[str, list[WatchlistEntry]] = defaultdict(list)
    for entry in watchlist_entries:
        subject_entries[entry.subject_key].append(entry)

    candidates: list[SanctionsCandidate] = []

    # 3. Deterministic candidate generation across sorted subject keys
    for subj_key in sorted(subject_entries.keys()):
        entries_for_subj = subject_entries[subj_key]
        subject_dob = entries_for_subj[0].date_of_birth

        # Find all entries where normalized listed name equals normalized customer
        matched_for_subj: list[WatchlistEntry] = []
        for entry in entries_for_subj:
            if normalize_full_name(entry.listed_name) == norm_customer:
                matched_for_subj.append(entry)

        if matched_for_subj:
            # Deterministic sorting: primary first, then listed_name, then entry_id
            matched_for_subj.sort(
                key=lambda e: (
                    0 if e.name_type == NameType.PRIMARY else 1,
                    e.listed_name,
                    str(e.entry_id),
                )
            )

            dob_comp = compare_dob(customer_dob, subject_dob)

            candidates.append(
                SanctionsCandidate(
                    subject_key=subj_key,
                    matched_entries=tuple(matched_for_subj),
                    dob_comparison=dob_comp,
                    subject_dob=subject_dob,
                    customer_dob=customer_dob,
                )
            )

    # 4. Form final result
    if candidates:
        outcome = ScreeningOutcome.CANDIDATE_MATCHES_FOUND
    else:
        outcome = ScreeningOutcome.NO_CANDIDATE_MATCH

    return SanctionsMatchResult(
        outcome=outcome,
        reason_code=None,
        candidates=tuple(candidates),
        watchlist_name=w_name,
        watchlist_version=w_ver,
        matching_rule_id=MATCHING_RULE_ID,
        normalization_version=NORMALIZATION_VERSION,
    )
