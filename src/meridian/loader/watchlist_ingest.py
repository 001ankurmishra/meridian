"""
Atomic, immutable loader for watchlist versions.

Validates the complete proposed version before writing and executes inserts in
a single transaction. Identical reloads are idempotent no-ops. Conflicting
reloads raise WatchlistVersionConflict.
"""

from dataclasses import dataclass
from typing import Sequence, Union

from sqlalchemy import Connection, Engine, text

from meridian.agents.sanctions.errors import WatchlistVersionConflict
from meridian.agents.sanctions.types import WatchlistEntry
from meridian.agents.sanctions.validation import validate_watchlist_entries


@dataclass(frozen=True)
class IngestResult:
    """Outcome of a watchlist version ingestion operation."""

    inserted: int
    already_existed: bool
    watchlist_name: str
    watchlist_version: str


def ingest_watchlist_version(
    target: Union[Engine, Connection],
    entries: Sequence[WatchlistEntry],
) -> IngestResult:
    """
    Ingests a complete, validated watchlist version in a single atomic transaction.

    Concurrency Note:
        Concurrent calls to `ingest_watchlist_version` for the same new version may
        both observe 0 rows and attempt concurrent inserts. The database constraints
        (primary key `entry_id` and unique `uq_watchlist_entries_natural_key`) will
        safely reject the losing transaction with an integrity violation and roll it
        back, preventing corrupted or partial versions. Per ADR-0008, advisory locks
        or coordination infrastructure are not introduced.

    Args:
        target: SQLAlchemy Engine or Connection.
        entries: Sequence of WatchlistEntry domain records for the full version.

    Returns:
        IngestResult indicating rows inserted and whether version already existed.

    Raises:
        WatchlistValidationError: If proposed version fails pre-write validation.
        WatchlistVersionConflict: If version exists with differing content or IDs.
    """
    # 1. Whole-version pre-write validation
    validate_watchlist_entries(entries, as_integrity_violation=False)

    watchlist_name = entries[0].watchlist_name
    watchlist_version = entries[0].watchlist_version

    if isinstance(target, Engine):
        with target.begin() as conn:
            return _execute_ingest(conn, entries, watchlist_name, watchlist_version)
    else:
        return _execute_ingest(target, entries, watchlist_name, watchlist_version)


def _execute_ingest(
    conn: Connection,
    entries: Sequence[WatchlistEntry],
    watchlist_name: str,
    watchlist_version: str,
) -> IngestResult:
    # 2. Check for existing version rows
    query = text(
        "SELECT entry_id, subject_key, name_type, listed_name, "
        "       date_of_birth, is_synthetic, source "
        "FROM watchlist_entries "
        "WHERE watchlist_name = :w_name AND watchlist_version = :w_ver "
        "ORDER BY entry_id"
    )
    existing_rows = conn.execute(
        query,
        {"w_name": watchlist_name, "w_ver": watchlist_version},
    ).fetchall()

    if existing_rows:
        # 3. Compare existing rows with proposed entries for identical reload
        existing_canonical = {
            (
                str(row.entry_id),
                row.subject_key,
                row.name_type,
                row.listed_name,
                row.date_of_birth,
                row.is_synthetic,
                row.source,
            )
            for row in existing_rows
        }
        proposed_canonical = {
            (
                str(e.entry_id),
                e.subject_key,
                (
                    e.name_type.value
                    if hasattr(e.name_type, "value")
                    else str(e.name_type)
                ),
                e.listed_name,
                e.date_of_birth,
                e.is_synthetic,
                e.source,
            )
            for e in entries
        }

        if (
            len(existing_rows) == len(entries)
            and existing_canonical == proposed_canonical
        ):
            # Idempotent identical reload
            return IngestResult(
                inserted=0,
                already_existed=True,
                watchlist_name=watchlist_name,
                watchlist_version=watchlist_version,
            )

        # Conflicting reload attempt
        raise WatchlistVersionConflict(
            f"Watchlist version '{watchlist_version}' for '{watchlist_name}' "
            f"already exists with differing content or IDs "
            f"({len(existing_rows)} existing vs {len(entries)} proposed)."
        )

    # 4. Insert all entries in the transaction (do not pass created_at explicitly)
    insert_stmt = text(
        "INSERT INTO watchlist_entries "
        "(entry_id, watchlist_name, watchlist_version, subject_key, name_type, "
        " listed_name, date_of_birth, is_synthetic, source) "
        "VALUES (:entry_id, :w_name, :w_ver, :subject_key, :name_type, "
        "        :listed_name, :dob, :is_synth, :source)"
    )

    for entry in entries:
        name_val = (
            entry.name_type.value
            if hasattr(entry.name_type, "value")
            else str(entry.name_type)
        )
        conn.execute(
            insert_stmt,
            {
                "entry_id": entry.entry_id,
                "w_name": entry.watchlist_name,
                "w_ver": entry.watchlist_version,
                "subject_key": entry.subject_key,
                "name_type": name_val,
                "listed_name": entry.listed_name,
                "dob": entry.date_of_birth,
                "is_synth": entry.is_synthetic,
                "source": entry.source,
            },
        )

    return IngestResult(
        inserted=len(entries),
        already_existed=False,
        watchlist_name=watchlist_name,
        watchlist_version=watchlist_version,
    )
