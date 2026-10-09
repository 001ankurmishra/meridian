"""
Whole-version validation for watchlist entries.

Enforces schema and ADR-0008 D5 invariants before database insertion (loader)
and upon database read (reader defense-in-depth).
"""

import uuid
from collections import defaultdict
from typing import Sequence

from meridian.agents.sanctions.errors import (
    WatchlistIntegrityViolation,
    WatchlistValidationError,
)
from meridian.agents.sanctions.normalization import normalize_full_name
from meridian.agents.sanctions.types import NameType, WatchlistEntry


def validate_watchlist_entries(
    entries: Sequence[WatchlistEntry],
    as_integrity_violation: bool = False,
) -> None:
    """
    Validates a complete proposed or loaded watchlist version.

    Args:
        entries: Sequence of WatchlistEntry objects to validate.
        as_integrity_violation: If True, raises WatchlistIntegrityViolation
            instead of WatchlistValidationError (for runtime reader check).

    Raises:
        WatchlistValidationError: When pre-load validation fails.
        WatchlistIntegrityViolation: When runtime loaded data validation fails.
    """
    error_cls = (
        WatchlistIntegrityViolation
        if as_integrity_violation
        else WatchlistValidationError
    )

    if not entries:
        raise error_cls("Proposed watchlist version contains zero entries.")

    first = entries[0]
    expected_name = first.watchlist_name
    expected_version = first.watchlist_version

    if not expected_name or not expected_name.strip():
        raise error_cls("Watchlist name must be a non-empty string.")

    if not expected_version or not expected_version.strip():
        raise error_cls("Watchlist version must be a non-empty string.")

    seen_entry_ids: set[uuid.UUID] = set()
    seen_natural_keys: set[tuple[str, str, str, str, str]] = set()
    subjects_primary_count: dict[str, int] = defaultdict(int)
    subjects_dob: dict[str, tuple[bool, object]] = {}

    for idx, entry in enumerate(entries):
        # 1. Uniform watchlist_name and watchlist_version
        if entry.watchlist_name != expected_name:
            raise error_cls(
                f"Entry at index {idx} has watchlist_name '{entry.watchlist_name}', "
                f"expected '{expected_name}'."
            )
        if entry.watchlist_version != expected_version:
            raise error_cls(
                f"Entry at index {idx} has watchlist_version "
                f"'{entry.watchlist_version}', expected '{expected_version}'."
            )

        # 2. Must be synthetic
        if not entry.is_synthetic:
            raise error_cls(
                f"Entry {entry.entry_id} must have is_synthetic=True."
            )

        # 3. Valid non-empty subject_key and source
        if not entry.subject_key or not entry.subject_key.strip():
            raise error_cls(f"Entry at index {idx} has empty subject_key.")
        if not entry.source or not entry.source.strip():
            raise error_cls(f"Entry {entry.entry_id} has empty source.")

        # 4. entry_id must be a valid UUID and unique within version
        if not isinstance(entry.entry_id, uuid.UUID):
            raise error_cls(
                f"Entry at index {idx} has invalid entry_id: {entry.entry_id}"
            )
        if entry.entry_id in seen_entry_ids:
            raise error_cls(
                f"Duplicate entry_id '{entry.entry_id}' in watchlist version."
            )
        seen_entry_ids.add(entry.entry_id)

        # 5. Valid name_type
        if isinstance(entry.name_type, NameType):
            name_type_val = entry.name_type.value
        elif isinstance(entry.name_type, str) and entry.name_type in (
            NameType.PRIMARY.value,
            NameType.ALIAS.value,
        ):
            name_type_val = entry.name_type
        else:
            raise error_cls(
                f"Entry {entry.entry_id} has invalid name_type: "
                f"'{entry.name_type}'."
            )

        # 6. Non-blank listed_name and non-empty after normalization
        if not entry.listed_name or not normalize_full_name(entry.listed_name):
            raise error_cls(
                f"Entry {entry.entry_id} listed_name '{entry.listed_name}' "
                "is empty after normalization."
            )

        # 7. Unique natural key
        natural_key = (
            entry.watchlist_name,
            entry.watchlist_version,
            entry.subject_key,
            name_type_val,
            entry.listed_name,
        )
        if natural_key in seen_natural_keys:
            raise error_cls(
                f"Duplicate natural key {natural_key} detected in watchlist."
            )
        seen_natural_keys.add(natural_key)

        # 8. Track primary names
        if name_type_val == NameType.PRIMARY.value:
            subjects_primary_count[entry.subject_key] += 1

        # 9. Track and verify DOB consistency across subject_key
        if entry.subject_key not in subjects_dob:
            subjects_dob[entry.subject_key] = (True, entry.date_of_birth)
        else:
            expected_dob = subjects_dob[entry.subject_key][1]
            if entry.date_of_birth != expected_dob:
                raise error_cls(
                    f"Inconsistent date_of_birth for subject_key "
                    f"'{entry.subject_key}': '{entry.date_of_birth}' "
                    f"vs '{expected_dob}'."
                )

    # 10. Exactly one primary per subject_key
    for subject_key in subjects_dob:
        primary_count = subjects_primary_count[subject_key]
        if primary_count != 1:
            raise error_cls(
                f"Subject '{subject_key}' has {primary_count} primary entries, "
                "exactly 1 is required."
            )
