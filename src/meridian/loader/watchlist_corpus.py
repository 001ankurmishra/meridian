"""
Deterministic synthetic watchlist corpus for F11 sanctions screening.

All subjects and listed names in this corpus are fictional, synthetic constructs
created exclusively for automated integration testing and evaluation.
No real personal data or live sanctions data is contained or referenced.
"""

import datetime
import hashlib
import uuid
from typing import Sequence

from meridian.agents.sanctions.types import NameType, WatchlistEntry

SYNTHETIC_WATCHLIST_NAME: str = "meridian_synthetic_watchlist"
SYNTHETIC_WATCHLIST_VERSION: str = "v1"
SYNTHETIC_WATCHLIST_SOURCE: str = "MERIDIAN_SYNTHETIC_WATCHLIST_v1"

# Fixed UUIDv5 namespace for reproducible entry IDs
NAMESPACE_MERIDIAN_WATCHLIST: uuid.UUID = uuid.UUID(
    "3d2b7812-70b5-4bfe-995b-010419d85449"
)


def make_entry_id(
    watchlist_name: str,
    watchlist_version: str,
    subject_key: str,
    name_type: NameType,
    listed_name: str,
) -> uuid.UUID:
    """Generate deterministic UUIDv5 entry identifier from natural key."""
    natural_key = (
        f"{watchlist_name}:{watchlist_version}:{subject_key}:"
        f"{name_type.value}:{listed_name}"
    )
    return uuid.uuid5(NAMESPACE_MERIDIAN_WATCHLIST, natural_key)


def compute_corpus_content_hash(entries: Sequence[WatchlistEntry]) -> str:
    """
    Computes a deterministic SHA-256 digest of canonical entries serialization.
    """
    lines = [
        f"{e.entry_id}|{e.watchlist_name}|{e.watchlist_version}|{e.subject_key}|"
        f"{e.name_type.value}|{e.listed_name}|{e.date_of_birth}|"
        f"{e.is_synthetic}|{e.source}"
        for e in entries
    ]
    content = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


_RAW_CORPUS_DEFINITIONS: tuple[
    tuple[str, NameType, str, datetime.date | None], ...
] = (
    ("SUBJ-SYNTH-001", NameType.PRIMARY, "Aurelius Vance", datetime.date(1980, 5, 15)),
    ("SUBJ-SYNTH-001", NameType.ALIAS, "A. Vance", datetime.date(1980, 5, 15)),
    ("SUBJ-SYNTH-001", NameType.ALIAS, "Aurel Vance", datetime.date(1980, 5, 15)),
    ("SUBJ-SYNTH-002", NameType.PRIMARY, "Elena Rostova", datetime.date(1985, 3, 20)),
    ("SUBJ-SYNTH-002", NameType.ALIAS, "Elena Rostoff", datetime.date(1985, 3, 20)),
    ("SUBJ-SYNTH-003", NameType.PRIMARY, "Elena Rostova", datetime.date(1972, 11, 10)),
    ("SUBJ-SYNTH-003", NameType.ALIAS, "E. Rostova", datetime.date(1972, 11, 10)),
    ("SUBJ-SYNTH-004", NameType.PRIMARY, "Kasimir Drake", datetime.date(1992, 8, 4)),
    ("SUBJ-SYNTH-004", NameType.ALIAS, "Kaz Drake", datetime.date(1992, 8, 4)),
    ("SUBJ-SYNTH-005", NameType.PRIMARY, "Tariq Mansoor", None),
)


def _build_synthetic_corpus() -> tuple[WatchlistEntry, ...]:
    entries: list[WatchlistEntry] = []
    for subj_key, name_type, listed_name, dob in _RAW_CORPUS_DEFINITIONS:
        entry_id = make_entry_id(
            SYNTHETIC_WATCHLIST_NAME,
            SYNTHETIC_WATCHLIST_VERSION,
            subj_key,
            name_type,
            listed_name,
        )
        entries.append(
            WatchlistEntry(
                entry_id=entry_id,
                watchlist_name=SYNTHETIC_WATCHLIST_NAME,
                watchlist_version=SYNTHETIC_WATCHLIST_VERSION,
                subject_key=subj_key,
                name_type=name_type,
                listed_name=listed_name,
                date_of_birth=dob,
                is_synthetic=True,
                source=SYNTHETIC_WATCHLIST_SOURCE,
                created_at=None,
            )
        )
    return tuple(entries)


SYNTHETIC_WATCHLIST_CORPUS: tuple[WatchlistEntry, ...] = (
    _build_synthetic_corpus()
)
SYNTHETIC_WATCHLIST_CONTENT_HASH: str = compute_corpus_content_hash(
    SYNTHETIC_WATCHLIST_CORPUS
)


def get_synthetic_watchlist_corpus() -> tuple[WatchlistEntry, ...]:
    """Return a fresh immutable copy of the synthetic watchlist entries."""
    return SYNTHETIC_WATCHLIST_CORPUS
