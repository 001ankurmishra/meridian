"""Report authoring layer."""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Final

from sqlalchemy import Connection, text

from meridian.agents.policy.policy_agent import PolicyEvidenceFound
from meridian.agents.report.outcome import InvestigationOutcome
from meridian.agents.transaction.amount_deviation import AmountDeviationComputed
from meridian.evidence.evidence import (
    EVIDENCE_TYPE_ALERTED_TRANSACTION,
    EVIDENCE_TYPE_AMOUNT_DEVIATION_INPUT,
    EVIDENCE_TYPE_POLICY_CHUNK,
    REFERENCE_TABLE_DOCUMENT_CHUNKS,
    REFERENCE_TABLE_TRANSACTIONS,
    record_evidence_with_connection,
)
from meridian.findings.findings import (
    evaluate_evidence_sufficiency,
    record_finding_with_connection,
)

PROTOTYPE_CONFIDENCE_FLOOR: Final[str] = "LOW"


class FindingCategory(str, Enum):
    """Internal category for finding drafts."""

    INVESTIGATIVE = "INVESTIGATIVE"
    REFERENCE = "REFERENCE"


@dataclass(frozen=True)
class EvidenceDraft:
    key: str
    evidence_type: str
    reference_table: str
    reference_id: uuid.UUID
    agent_run_id: uuid.UUID


@dataclass(frozen=True)
class FindingDraft:
    category: FindingCategory
    observed_fact: str
    derived_signal: str | None
    interpretation: str | None
    evidence_keys: tuple[str, ...]
    confidence: str


@dataclass(frozen=True)
class AuthoringDrafts:
    evidence: tuple[EvidenceDraft, ...]
    findings: tuple[FindingDraft, ...]


@dataclass(frozen=True)
class AuthoringResult:
    evidence_ids: tuple[uuid.UUID, ...]
    finding_ids: tuple[uuid.UUID, ...]


class AuthoringError(Exception):
    """Base exception for authoring errors."""


class AuthoringAlreadyPerformedError(AuthoringError):
    """Raised when evidence or findings already exist for the investigation run."""


class AuthoringInvariantError(AuthoringError):
    """Raised when invariant conditions are violated during authoring."""


def _format_decimal(value: Decimal) -> str:
    """Format decimal quantized to 2dp."""
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


def build_authoring_drafts(outcome: InvestigationOutcome) -> AuthoringDrafts:
    """Build evidence and findings drafts deterministically from the outcome."""
    evidence: list[EvidenceDraft] = []
    findings: list[FindingDraft] = []

    # Computed transaction outcome
    if outcome.transaction is not None and isinstance(
        outcome.transaction.result, AmountDeviationComputed
    ):
        result = outcome.transaction.result
        agent_run_id = outcome.transaction.agent_run_id

        alerted_key = f"alerted_{result.alerted_transaction_id}"
        evidence.append(
            EvidenceDraft(
                key=alerted_key,
                evidence_type=EVIDENCE_TYPE_ALERTED_TRANSACTION,
                reference_table=REFERENCE_TABLE_TRANSACTIONS,
                reference_id=result.alerted_transaction_id,
                agent_run_id=agent_run_id,
            )
        )

        input_keys = []
        for src_id in sorted(result.source_transaction_ids):
            src_key = f"input_{src_id}"
            evidence.append(
                EvidenceDraft(
                    key=src_key,
                    evidence_type=EVIDENCE_TYPE_AMOUNT_DEVIATION_INPUT,
                    reference_table=REFERENCE_TABLE_TRANSACTIONS,
                    reference_id=src_id,
                    agent_run_id=agent_run_id,
                )
            )
            input_keys.append(src_key)

        evidence_keys = tuple([alerted_key] + input_keys)

        amt_str = _format_decimal(result.alerted_amount)
        avg_str = _format_decimal(result.historical_average)
        dev_str = str(result.deviation_multiple)
        currency = result.currency

        observed_fact = (
            f"Transaction {result.alerted_transaction_id} from source account "
            f"{result.source_account_id} has a recorded amount of {amt_str} {currency}."
        )
        derived_signal = (
            f"The recorded amount is {dev_str} times the mean amount ({avg_str} {currency}) "  # noqa: E501
            f"of {result.historical_transaction_count} outgoing transaction(s) from the "  # noqa: E501
            "customer's accounts in the 90 days before this transaction."
        )
        interpretation = (
            "This describes relative size only. No validated threshold defines an "
            "unusual deviation (PROTOTYPE), so no conclusion about the activity is drawn."  # noqa: E501
        )

        findings.append(
            FindingDraft(
                category=FindingCategory.INVESTIGATIVE,
                observed_fact=observed_fact,
                derived_signal=derived_signal,
                interpretation=interpretation,
                evidence_keys=evidence_keys,
                confidence=PROTOTYPE_CONFIDENCE_FLOOR,
            )
        )

    # Policy found outcome
    if (
        outcome.policy is not None
        and isinstance(outcome.policy.result, PolicyEvidenceFound)
        and len(outcome.policy.result.citations) > 0
    ):
        alert_type = outcome.alert_type
        if not isinstance(alert_type, str) or not alert_type.strip():
            raise AuthoringInvariantError(
                "alert_type must be a non-empty string to author policy finding."
            )

        policy_result = outcome.policy.result
        agent_run_id = outcome.policy.agent_run_id

        policy_keys = []
        for i, citation in enumerate(policy_result.citations):
            key = f"policy_{citation.chunk_id}_{i}"
            evidence.append(
                EvidenceDraft(
                    key=key,
                    evidence_type=EVIDENCE_TYPE_POLICY_CHUNK,
                    reference_table=REFERENCE_TABLE_DOCUMENT_CHUNKS,
                    reference_id=citation.chunk_id,
                    agent_run_id=agent_run_id,
                )
            )
            policy_keys.append(key)

        items = []
        scores = []
        for citation in policy_result.citations:
            scores.append(citation.rrf_score)
            if citation.is_synthetic:
                items.append(
                    f"{citation.title} (version {citation.version}, chunk {citation.chunk_index}, synthetic)"  # noqa: E501
                )
            else:
                items.append(
                    f"{citation.title} (version {citation.version}, chunk {citation.chunk_index})"  # noqa: E501
                )

        items_str = "; ".join(items)
        observed_fact = (
            f"Policy reference: retrieval for alert type '{alert_type}' returned "
            f"{len(policy_result.citations)} passage(s): {items_str}."
        )

        min_score = min(scores)
        max_score = max(scores)
        derived_signal = (
            "Passages were ranked by combined lexical and vector retrieval; "
            f"fusion scores range from {min_score:.4f} to {max_score:.4f}."
        )

        interpretation = (
            "Reference material only; not an assessment of the customer's activity. "
            "The retrieval-confidence threshold is an unvalidated PROTOTYPE value, "
            "so relevance to this alert has not been established."
        )

        findings.append(
            FindingDraft(
                category=FindingCategory.REFERENCE,
                observed_fact=observed_fact,
                derived_signal=derived_signal,
                interpretation=interpretation,
                evidence_keys=tuple(policy_keys),
                confidence=PROTOTYPE_CONFIDENCE_FLOOR,
            )
        )

    drafts = AuthoringDrafts(
        evidence=tuple(evidence),
        findings=tuple(findings),
    )

    # Invariants
    all_evidence_keys = {e.key for e in drafts.evidence}
    all_evidence_types = {e.key: e.evidence_type for e in drafts.evidence}

    for f in drafts.findings:
        if not f.evidence_keys:
            raise AuthoringInvariantError("Finding draft has zero evidence keys.")
        if len(set(f.evidence_keys)) != len(f.evidence_keys):
            raise AuthoringInvariantError("Finding draft has duplicate evidence keys.")
        for k in f.evidence_keys:
            if k not in all_evidence_keys:
                raise AuthoringInvariantError(f"Evidence key {k} not found in drafts.")

        has_policy = any(
            all_evidence_types[k] == EVIDENCE_TYPE_POLICY_CHUNK for k in f.evidence_keys
        )
        if f.category == FindingCategory.REFERENCE and not all(
            all_evidence_types[k] == EVIDENCE_TYPE_POLICY_CHUNK for k in f.evidence_keys
        ):
            raise AuthoringInvariantError(
                "REFERENCE finding cites non-policy evidence."
            )
        if f.category == FindingCategory.INVESTIGATIVE and has_policy:
            raise AuthoringInvariantError(
                "INVESTIGATIVE finding cites policy evidence."
            )

        if f.confidence != PROTOTYPE_CONFIDENCE_FLOOR:
            raise AuthoringInvariantError(
                "Finding confidence violates prototype floor."
            )

    return drafts


def author_investigation_records(
    conn: Connection, outcome: InvestigationOutcome
) -> AuthoringResult:
    """Author evidence and findings from an investigation outcome."""

    # 1. Guard
    run_id = outcome.investigation_run_id
    evidence_count = conn.execute(
        text("SELECT count(*) FROM evidence WHERE investigation_run_id = :run_id"),
        {"run_id": run_id},
    ).scalar()
    findings_count = conn.execute(
        text("SELECT count(*) FROM findings WHERE investigation_run_id = :run_id"),
        {"run_id": run_id},
    ).scalar()

    # Need to check properly if count is truthy
    # scalar returns an int in this case
    if (evidence_count and evidence_count > 0) or (
        findings_count and findings_count > 0
    ):
        raise AuthoringAlreadyPerformedError(
            "Evidence or findings already exist for this investigation run."
        )

    # 2. Build drafts
    drafts = build_authoring_drafts(outcome)

    # 3. If no drafts
    if not drafts.evidence and not drafts.findings:
        return AuthoringResult(evidence_ids=(), finding_ids=())

    # 4. Insert evidence
    resolved_keys: dict[str, uuid.UUID] = {}
    evidence_ids: list[uuid.UUID] = []

    for ed in drafts.evidence:
        record = record_evidence_with_connection(
            conn=conn,
            investigation_run_id=run_id,
            evidence_type=ed.evidence_type,
            reference_table=ed.reference_table,
            reference_id=ed.reference_id,
            produced_by_agent_run_id=ed.agent_run_id,
        )
        resolved_keys[ed.key] = record.evidence_id
        evidence_ids.append(record.evidence_id)

    # 5. For each finding
    finding_ids: list[uuid.UUID] = []
    for fd in drafts.findings:
        f_evidence_ids = [resolved_keys[k] for k in fd.evidence_keys]

        if not evaluate_evidence_sufficiency(f_evidence_ids):
            raise AuthoringInvariantError(
                "Evidence is not sufficient for this finding."
            )

        record_f = record_finding_with_connection(
            conn=conn,
            investigation_run_id=run_id,
            observed_fact=fd.observed_fact,
            derived_signal=fd.derived_signal,
            interpretation=fd.interpretation,
            evidence_ids=f_evidence_ids,
            confidence=fd.confidence,
        )
        finding_ids.append(record_f.finding_id)

    # 6. Return
    return AuthoringResult(
        evidence_ids=tuple(evidence_ids),
        finding_ids=tuple(finding_ids),
    )
