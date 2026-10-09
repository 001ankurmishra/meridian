"""
Read-only exact-version reader for watchlist entries.

Requires explicit (watchlist_name, watchlist_version) parameters. Queries only
that exact identity using bound parameters (no MAX, version ordering,
or implicit defaults).
Zero rows raise WatchlistVersionNotLoaded. Loaded rows are validated in memory
as defense in depth; corrupt rows raise WatchlistIntegrityViolation.
"""

import uuid
from typing import Union

from sqlalchemy import Connection, Engine, text

from meridian.agents.sanctions.errors import (
    WatchlistIntegrityViolation,
    WatchlistVersionNotLoaded,
)
from meridian.agents.sanctions.types import NameType, WatchlistEntry
from meridian.agents.sanctions.validation import validate_watchlist_entries


def read_watchlist_version(
    target: Union[Engine, Connection],
    watchlist_name: str,
    watchlist_version: str,
) -> tuple[WatchlistEntry, ...]:
    """
    Reads all entries for an exact, pinned watchlist version.

    Args:
        target: SQLAlchemy Engine or Connection (read-only access).
        watchlist_name: Exact name of the watchlist (required, no default).
        watchlist_version: Exact version string of the watchlist (required, no default).

    Returns:
        Immutable tuple of validated WatchlistEntry domain records.

    Raises:
        ValueError: If watchlist_name or watchlist_version is missing or empty.
        WatchlistVersionNotLoaded: If zero rows exist for the specified version.
        WatchlistIntegrityViolation: If loaded data fails whole-version validation.
    """
    if not isinstance(watchlist_name, str) or not watchlist_name.strip():
        raise ValueError("Explicit non-empty watchlist_name is required.")
    if not isinstance(watchlist_version, str) or not watchlist_version.strip():
        raise ValueError("Explicit non-empty watchlist_version is required.")

    query = text(
        "SELECT entry_id, watchlist_name, watchlist_version, subject_key, "
        "       name_type, listed_name, date_of_birth, is_synthetic, "
        "       source, created_at "
        "FROM watchlist_entries "
        "WHERE watchlist_name = :w_name AND watchlist_version = :w_ver "
        "ORDER BY subject_key, name_type, listed_name, entry_id"
    )

    if isinstance(target, Engine):
        with target.connect() as conn:
            rows = conn.execute(
                query,
                {"w_name": watchlist_name, "w_ver": watchlist_version},
            ).fetchall()
    else:
        rows = target.execute(
            query,
            {"w_name": watchlist_name, "w_ver": watchlist_version},
        ).fetchall()

    if not rows:
        raise WatchlistVersionNotLoaded(
            f"Watchlist '{watchlist_name}' version '{watchlist_version}' "
            "is not loaded."
        )

    entries: list[WatchlistEntry] = []
    for r in rows:
        try:
            entry_id = (
                r.entry_id
                if isinstance(r.entry_id, uuid.UUID)
                else uuid.UUID(str(r.entry_id))
            )
            name_type = NameType(r.name_type)
            entries.append(
                WatchlistEntry(
                    entry_id=entry_id,
                    watchlist_name=r.watchlist_name,
                    watchlist_version=r.watchlist_version,
                    subject_key=r.subject_key,
                    name_type=name_type,
                    listed_name=r.listed_name,
                    date_of_birth=r.date_of_birth,
                    is_synthetic=bool(r.is_synthetic),
                    source=r.source,
                    created_at=r.created_at,
                )
            )
        except Exception as e:
            raise WatchlistIntegrityViolation(
                f"Malformed watchlist entry data: {e}"
            ) from e

    # Whole-version defense-in-depth validation
    validate_watchlist_entries(entries, as_integrity_violation=True)

    return tuple(entries)
