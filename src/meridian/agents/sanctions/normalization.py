"""
Normalization adapter for F11 sanctions screening.

This is the ONLY module within meridian.agents.sanctions permitted to import
from meridian.entity_resolution. It reuses the single-pass normalizer
(NFKC -> casefold -> whitespace collapse) and verifies version compatibility.
"""

from meridian.agents.sanctions.errors import NormalizationVersionMismatch
from meridian.entity_resolution.matching import (
    NORMALIZATION_VERSION as IMPORTED_NORMALIZATION_VERSION,
)
from meridian.entity_resolution.matching import (
    normalize_full_name,
)

EXPECTED_NORMALIZATION_VERSION = "v1"

if IMPORTED_NORMALIZATION_VERSION != EXPECTED_NORMALIZATION_VERSION:
    raise NormalizationVersionMismatch(
        f"Expected normalization version '{EXPECTED_NORMALIZATION_VERSION}', "
        f"but entity_resolution provides '{IMPORTED_NORMALIZATION_VERSION}'."
    )

NORMALIZATION_VERSION = IMPORTED_NORMALIZATION_VERSION

__all__ = [
    "EXPECTED_NORMALIZATION_VERSION",
    "NORMALIZATION_VERSION",
    "normalize_full_name",
]
