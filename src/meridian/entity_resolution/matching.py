import unicodedata
import uuid
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import Engine, text

RULE_ID = "exact_norm_name_exact_dob_v1"
NORMALIZATION_VERSION = "v1"
MATCHED_FIELDS = ("normalized_full_name", "date_of_birth")

@dataclass(frozen=True)
class CustomerIdentityRecord:
    customer_id: uuid.UUID
    full_name: str | None
    date_of_birth: str | None

@dataclass(frozen=True)
class CandidateLink:
    customer_id_a: uuid.UUID
    customer_id_b: uuid.UUID
    rule_id: str
    normalization_version: str
    matched_fields: tuple[str, ...]

@dataclass(frozen=True)
class IneligibleRecord:
    customer_id: uuid.UUID
    reasons: tuple[str, ...]

@dataclass
class ResolutionResult:
    candidates: list[CandidateLink]
    ineligible: list[IneligibleRecord]

def normalize_full_name(name: str | None) -> str:
    if not name:
        return ""
    # NFKC -> casefold -> whitespace collapse
    nfkc = unicodedata.normalize("NFKC", name)
    casefolded = nfkc.casefold()
    return " ".join(casefolded.split())

def find_candidate_links(records: Iterable[CustomerIdentityRecord]) -> ResolutionResult:
    candidates: list[CandidateLink] = []
    ineligible: list[IneligibleRecord] = []

    seen_ids: set[uuid.UUID] = set()
    buckets: dict[tuple[str, str], list[uuid.UUID]] = {}

    for r in records:
        if r.customer_id in seen_ids:
            raise ValueError(f"Repeated customer_id {r.customer_id}")
        seen_ids.add(r.customer_id)

        reasons: list[str] = []
        if r.date_of_birth is None:
            reasons.append("dob_null")

        norm_name = ""
        if r.full_name is None:
            reasons.append("name_null")
        else:
            norm_name = normalize_full_name(r.full_name)
            if not norm_name:
                reasons.append("name_empty_after_normalization")

        if reasons:
            ineligible.append(IneligibleRecord(r.customer_id, tuple(reasons)))
            continue

        key = (norm_name, str(r.date_of_birth))
        buckets.setdefault(key, []).append(r.customer_id)

    for key, ids in sorted(buckets.items()):
        if len(ids) > 1:
            sorted_ids = sorted(ids)
            for i in range(len(sorted_ids)):
                for j in range(i + 1, len(sorted_ids)):
                    candidates.append(
                        CandidateLink(
                            customer_id_a=sorted_ids[i],
                            customer_id_b=sorted_ids[j],
                            rule_id=RULE_ID,
                            normalization_version=NORMALIZATION_VERSION,
                            matched_fields=MATCHED_FIELDS,
                        )
                    )

    ineligible.sort(key=lambda x: x.customer_id)
    return ResolutionResult(candidates, ineligible)

def compute_er_candidates(engine: Engine) -> ResolutionResult:
    records = []
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT customer_id, full_name, date_of_birth FROM customers")
        )
        for row in result:
            records.append(
                CustomerIdentityRecord(
                    customer_id=row.customer_id,
                    full_name=row.full_name,
                    date_of_birth=row.date_of_birth,
                )
            )
    return find_candidate_links(records)
