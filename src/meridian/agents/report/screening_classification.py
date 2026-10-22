"""Deterministic classification and section rendering for F11 watchlist screening.

Implements the seven-state contract from ADR-0008 D10 and
docs/AI_SAFETY_AND_GUARDRAILS.md §6.1.3.

This module is read-only and pure; it performs no database mutations.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Final


class WatchlistScreeningState(str, Enum):
    """The 7 classification states defined in ADR-0008 D10."""

    CANDIDATE_MATCHES_FOUND = "CANDIDATE_MATCHES_FOUND"
    NO_CANDIDATE_MATCH = "NO_CANDIDATE_MATCH"
    NOT_PERFORMED = "NOT_PERFORMED"
    SCREENING_ERROR = "SCREENING_ERROR"
    INCONSISTENT_MISSING_RESULT = "INCONSISTENT_MISSING_RESULT"
    SCREENING_NOT_RECORDED = "SCREENING_NOT_RECORDED"
    INCONSISTENT_INVALID_ROW = "INCONSISTENT_INVALID_ROW"


# Alias for compatibility if referenced as D10ScreeningState
D10ScreeningState = WatchlistScreeningState

VALID_ABSTENTION_REASON_CODES: Final[frozenset[str]] = frozenset(
    {
        "CUSTOMER_NAME_MISSING",
        "CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION",
        "WATCHLIST_VERSION_NOT_LOADED",
    }
)


@dataclass(frozen=True)
class ScreeningResultRow:
    """Read-only container for a persisted screening_results record."""

    screening_result_id: uuid.UUID
    investigation_run_id: uuid.UUID
    agent_run_id: uuid.UUID
    outcome: str
    reason_code: str | None
    candidate_count: int
    watchlist_name: str
    watchlist_version: str
    matching_rule_id: str
    normalization_version: str


@dataclass(frozen=True)
class SanctionsAgentRunInfo:
    """Read-only summary of an agent_runs row for SanctionsAgent."""

    agent_run_id: uuid.UUID
    agent_name: str
    status: str
    investigation_run_id: uuid.UUID


@dataclass(frozen=True)
class WatchlistScreeningSection:
    """The mandatory watchlist screening section of an InvestigationReport.

    Preserves ADR-0008 D10:
    - Never infers domain outcome from agent_runs, evidence, or findings.
    - Uses exact fixed wording templates for missing and inconsistent records.
    - Preserves distinction between candidate matches and confirmed identity.
    - Mandates human review.
    - Never exposes customer PII or sensitive watchlist identifiers.
    """

    state: WatchlistScreeningState
    rendered_text: str
    classification_branch: int
    outcome: str | None = None
    reason_code: str | None = None
    candidate_count: int | None = None
    watchlist_name: str | None = None
    watchlist_version: str | None = None
    matching_rule_id: str | None = None
    normalization_version: str | None = None
    agent_run_id: uuid.UUID | None = None

    @property
    def is_inconsistent(self) -> bool:
        """True if the classification corresponds to an inconsistent record."""
        return self.state in (
            WatchlistScreeningState.INCONSISTENT_MISSING_RESULT,
            WatchlistScreeningState.INCONSISTENT_INVALID_ROW,
        )


def classify_screening_state(
    *,
    screening_result: ScreeningResultRow | None,
    referenced_agent_run: SanctionsAgentRunInfo | None,
    all_sanctions_agent_runs: tuple[SanctionsAgentRunInfo, ...],
    candidate_finding_count: int,
) -> WatchlistScreeningSection:
    """Deterministically classify screening state according to ADR-0008 D10.

    Args:
        screening_result: Persisted screening_results row for the
            investigation run, if any.
        referenced_agent_run: The agent_runs row referenced by
            screening_result.agent_run_id, if screening_result exists.
        all_sanctions_agent_runs: All agent_runs rows with agent_name =
            'SanctionsAgent' for the investigation run.
        candidate_finding_count: Number of investigative findings in this
            investigation run that link watchlist_entry evidence.

    Returns:
        A WatchlistScreeningSection with deterministic state and rendered_text.
    """
    if screening_result is not None:
        # Check referenced run validity:
        # 1. referenced_agent_run exists
        # 2. agent_name == "SanctionsAgent"
        # 3. investigation_run_id matches
        # 4. status == "SUCCESS"
        referenced_run_valid = (
            referenced_agent_run is not None
            and referenced_agent_run.agent_name == "SanctionsAgent"
            and referenced_agent_run.investigation_run_id
            == screening_result.investigation_run_id
            and referenced_agent_run.status == "SUCCESS"
        )

        # Check candidate count consistency against authored candidate findings
        counts_consistent = (
            screening_result.candidate_count >= 0
            and screening_result.candidate_count == candidate_finding_count
        )

        if not referenced_run_valid or not counts_consistent:
            return WatchlistScreeningSection(
                state=WatchlistScreeningState.INCONSISTENT_INVALID_ROW,
                rendered_text="Inconsistent screening record. Not determined.",
                classification_branch=7,
                outcome=screening_result.outcome,
                reason_code=screening_result.reason_code,
                candidate_count=screening_result.candidate_count,
                watchlist_name=screening_result.watchlist_name,
                watchlist_version=screening_result.watchlist_version,
                matching_rule_id=screening_result.matching_rule_id,
                normalization_version=screening_result.normalization_version,
                agent_run_id=screening_result.agent_run_id,
            )

        # Consistent row cases:
        if screening_result.outcome == "CANDIDATE_MATCHES_FOUND":
            if (
                screening_result.candidate_count > 0
                and screening_result.reason_code is None
            ):
                return WatchlistScreeningSection(
                    state=WatchlistScreeningState.CANDIDATE_MATCHES_FOUND,
                    rendered_text=(
                        f"{screening_result.candidate_count} candidate match(es) "
                        f"on synthetic list {screening_result.watchlist_name} "
                        f"{screening_result.watchlist_version} under rule "
                        f"{screening_result.matching_rule_id}. "
                        "Candidate for human review; not an identity or "
                        "sanctions determination."
                    ),
                    classification_branch=1,
                    outcome=screening_result.outcome,
                    reason_code=None,
                    candidate_count=screening_result.candidate_count,
                    watchlist_name=screening_result.watchlist_name,
                    watchlist_version=screening_result.watchlist_version,
                    matching_rule_id=screening_result.matching_rule_id,
                    normalization_version=screening_result.normalization_version,
                    agent_run_id=screening_result.agent_run_id,
                )
            else:
                return WatchlistScreeningSection(
                    state=WatchlistScreeningState.INCONSISTENT_INVALID_ROW,
                    rendered_text="Inconsistent screening record. Not determined.",
                    classification_branch=7,
                    outcome=screening_result.outcome,
                    agent_run_id=screening_result.agent_run_id,
                )

        elif screening_result.outcome == "NO_CANDIDATE_MATCH":
            if (
                screening_result.candidate_count == 0
                and screening_result.reason_code is None
            ):
                return WatchlistScreeningSection(
                    state=WatchlistScreeningState.NO_CANDIDATE_MATCH,
                    rendered_text=(
                        f"No candidate match against synthetic list "
                        f"{screening_result.watchlist_name} "
                        f"{screening_result.watchlist_version}. "
                        "This is not a clearance."
                    ),
                    classification_branch=2,
                    outcome=screening_result.outcome,
                    reason_code=None,
                    candidate_count=0,
                    watchlist_name=screening_result.watchlist_name,
                    watchlist_version=screening_result.watchlist_version,
                    matching_rule_id=screening_result.matching_rule_id,
                    normalization_version=screening_result.normalization_version,
                    agent_run_id=screening_result.agent_run_id,
                )
            else:
                return WatchlistScreeningSection(
                    state=WatchlistScreeningState.INCONSISTENT_INVALID_ROW,
                    rendered_text="Inconsistent screening record. Not determined.",
                    classification_branch=7,
                    outcome=screening_result.outcome,
                    agent_run_id=screening_result.agent_run_id,
                )

        elif screening_result.outcome == "NOT_PERFORMED":
            if (
                screening_result.candidate_count == 0
                and screening_result.reason_code in VALID_ABSTENTION_REASON_CODES
            ):
                return WatchlistScreeningSection(
                    state=WatchlistScreeningState.NOT_PERFORMED,
                    rendered_text=f"Not determined: {screening_result.reason_code}.",
                    classification_branch=3,
                    outcome=screening_result.outcome,
                    reason_code=screening_result.reason_code,
                    candidate_count=0,
                    watchlist_name=screening_result.watchlist_name,
                    watchlist_version=screening_result.watchlist_version,
                    matching_rule_id=screening_result.matching_rule_id,
                    normalization_version=screening_result.normalization_version,
                    agent_run_id=screening_result.agent_run_id,
                )
            else:
                return WatchlistScreeningSection(
                    state=WatchlistScreeningState.INCONSISTENT_INVALID_ROW,
                    rendered_text="Inconsistent screening record. Not determined.",
                    classification_branch=7,
                    outcome=screening_result.outcome,
                    agent_run_id=screening_result.agent_run_id,
                )

        else:
            return WatchlistScreeningSection(
                state=WatchlistScreeningState.INCONSISTENT_INVALID_ROW,
                rendered_text="Inconsistent screening record. Not determined.",
                classification_branch=7,
                outcome=screening_result.outcome,
                agent_run_id=screening_result.agent_run_id,
            )

    # screening_result is None cases (ADR-0008 D10):
    if not all_sanctions_agent_runs:
        # Branch 6: No row; no SanctionsAgent run for the same investigation_run_id
        return WatchlistScreeningSection(
            state=WatchlistScreeningState.SCREENING_NOT_RECORDED,
            rendered_text="Screening not recorded. Not determined.",
            classification_branch=6,
        )

    # If any SanctionsAgent run has status SUCCESS or PARTIAL:
    # Branch 5: No row; a SanctionsAgent run for the same inv_run with SUCCESS/PARTIAL
    has_success_or_partial = any(
        r.status in ("SUCCESS", "PARTIAL") for r in all_sanctions_agent_runs
    )
    if has_success_or_partial:
        return WatchlistScreeningSection(
            state=WatchlistScreeningState.INCONSISTENT_MISSING_RESULT,
            rendered_text="Inconsistent screening record. Not determined.",
            classification_branch=5,
        )

    # Branch 4: No row; SanctionsAgent run(s) with status FAILED
    all_failed = all(r.status == "FAILED" for r in all_sanctions_agent_runs)
    if all_failed:
        return WatchlistScreeningSection(
            state=WatchlistScreeningState.SCREENING_ERROR,
            rendered_text="Screening error. Not determined.",
            classification_branch=4,
        )

    # Fallback if any unknown agent run status
    return WatchlistScreeningSection(
        state=WatchlistScreeningState.INCONSISTENT_MISSING_RESULT,
        rendered_text="Inconsistent screening record. Not determined.",
        classification_branch=5,
    )
