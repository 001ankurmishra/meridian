"""
Tests for the maintainer-approved replacement typed-result contract (Task 23b).

This is an approved replacement contract, not a recovery of the original
Task 23 contract (whose text is unrecoverable).

Verifies:
- LoadedWatchlistVersion structural invariants and runtime immutability
- WatchlistVersionNotLoaded is a returned data variant, not an exception
- The matcher turns a WatchlistVersionNotLoaded input into, and only into,
  NOT_PERFORMED(WATCHLIST_VERSION_NOT_LOADED), with precedence over
  customer-name abstentions
- New contract code never echoes entry or customer data in exception text
- The baseline output SHA is frozen
"""

import dataclasses
import datetime
import hashlib
from types import SimpleNamespace
from typing import Any

import pytest

import meridian.agents.sanctions as sanctions_pkg
from meridian.agents.sanctions import errors as sanctions_errors
from meridian.agents.sanctions.errors import (
    WatchlistIntegrityViolation,
    WatchlistValidationError,
)
from meridian.agents.sanctions.matching import match_customer_against_watchlist
from meridian.agents.sanctions.reader import read_watchlist_version
from meridian.agents.sanctions.types import (
    AbstentionReason,
    LoadedWatchlistVersion,
    ScreeningOutcome,
    WatchlistEntry,
    WatchlistReadResult,
    WatchlistVersionNotLoaded,
)
from meridian.fixtures.sanctions_baseline import (
    canonical_json,
    measure_sanctions_baseline,
)
from meridian.fixtures.sanctions_eval_corpus import get_sanctions_eval_cases
from meridian.loader.watchlist_corpus import (
    SYNTHETIC_WATCHLIST_CORPUS,
    SYNTHETIC_WATCHLIST_NAME,
    SYNTHETIC_WATCHLIST_VERSION,
)

FROZEN_BASELINE_SHA256 = (
    "30ddd37022b7c5990a31e25bea0148d5ea26068d1ca5736d35178052081b537b"
)
CANARY = "Canary Qwxzy 1971-03-09"


def _entries() -> tuple[WatchlistEntry, ...]:
    return tuple(SYNTHETIC_WATCHLIST_CORPUS)


def _loaded() -> LoadedWatchlistVersion:
    return LoadedWatchlistVersion(
        SYNTHETIC_WATCHLIST_NAME, SYNTHETIC_WATCHLIST_VERSION, _entries()
    )


# --------------------------------------------------------------------------
# LoadedWatchlistVersion
# --------------------------------------------------------------------------


def test_container_accepts_valid_version() -> None:
    lv = _loaded()
    assert lv.watchlist_name == SYNTHETIC_WATCHLIST_NAME
    assert lv.watchlist_version == SYNTHETIC_WATCHLIST_VERSION
    assert lv.entries == _entries()
    assert isinstance(lv.entries, tuple)


def test_container_rejects_empty_entries() -> None:
    with pytest.raises(WatchlistValidationError, match="at least one entry"):
        LoadedWatchlistVersion(
            SYNTHETIC_WATCHLIST_NAME, SYNTHETIC_WATCHLIST_VERSION, ()
        )


@pytest.mark.parametrize("bad", ["", "   ", "\t\n", None, 7])
def test_container_rejects_blank_or_non_string_identity(bad: Any) -> None:
    with pytest.raises(WatchlistValidationError, match="watchlist_name"):
        LoadedWatchlistVersion(bad, SYNTHETIC_WATCHLIST_VERSION, _entries())
    with pytest.raises(WatchlistValidationError, match="watchlist_version"):
        LoadedWatchlistVersion(SYNTHETIC_WATCHLIST_NAME, bad, _entries())


def test_container_rejects_entry_identity_mismatch() -> None:
    first, *rest = _entries()
    wrong_version = dataclasses.replace(first, watchlist_version="other_version")
    wrong_name = dataclasses.replace(first, watchlist_name="other_list")
    for bad_first in (wrong_version, wrong_name):
        with pytest.raises(WatchlistValidationError, match="must all carry"):
            LoadedWatchlistVersion(
                SYNTHETIC_WATCHLIST_NAME,
                SYNTHETIC_WATCHLIST_VERSION,
                (bad_first, *rest),
            )


def test_container_rejects_mismatch_in_last_entry_not_just_first() -> None:
    *head, last = _entries()
    bad_last = dataclasses.replace(last, watchlist_version="other_version")
    with pytest.raises(WatchlistValidationError, match="must all carry"):
        LoadedWatchlistVersion(
            SYNTHETIC_WATCHLIST_NAME,
            SYNTHETIC_WATCHLIST_VERSION,
            (*head, bad_last),
        )


@pytest.mark.parametrize("container_type", [list, set, frozenset])
def test_container_rejects_non_tuple_entries(container_type: Any) -> None:
    """Mutable (or unordered) sequences are rejected, never silently coerced."""
    with pytest.raises(WatchlistValidationError, match="must be a tuple"):
        LoadedWatchlistVersion(
            SYNTHETIC_WATCHLIST_NAME,
            SYNTHETIC_WATCHLIST_VERSION,
            container_type(_entries()),
        )


def test_container_rejects_non_entry_elements() -> None:
    with pytest.raises(WatchlistValidationError, match="only WatchlistEntry"):
        LoadedWatchlistVersion(
            SYNTHETIC_WATCHLIST_NAME,
            SYNTHETIC_WATCHLIST_VERSION,
            (*_entries(), "not-an-entry"),  # type: ignore[arg-type]
        )


def test_container_is_runtime_immutable() -> None:
    lv = _loaded()
    for field_name, value in (
        ("watchlist_name", "x"),
        ("watchlist_version", "x"),
        ("entries", ()),
    ):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(lv, field_name, value)
    with pytest.raises(TypeError):
        lv.entries[0] = lv.entries[1]  # type: ignore[index]
    with pytest.raises(AttributeError):
        lv.entries.append(lv.entries[0])  # type: ignore[attr-defined]


def test_container_error_text_never_echoes_entry_data() -> None:
    """A canary listed name and DOB must not appear in any container error."""
    first, *rest = _entries()
    leaky = dataclasses.replace(
        first,
        listed_name=CANARY,
        date_of_birth=datetime.date(1971, 3, 9),
        subject_key="SUBJ-CANARY",
        watchlist_version="other_version",
    )
    with pytest.raises(WatchlistValidationError) as exc:
        LoadedWatchlistVersion(
            SYNTHETIC_WATCHLIST_NAME,
            SYNTHETIC_WATCHLIST_VERSION,
            (leaky, *rest),
        )
    text = str(exc.value)
    for secret in (CANARY, "1971", "SUBJ-CANARY", "Canary"):
        assert secret not in text


# --------------------------------------------------------------------------
# WatchlistVersionNotLoaded variant
# --------------------------------------------------------------------------


def test_not_loaded_is_a_frozen_data_variant_not_an_exception() -> None:
    nl = WatchlistVersionNotLoaded("some_list", "v9")
    assert not isinstance(nl, BaseException)
    assert not issubclass(WatchlistVersionNotLoaded, BaseException)
    assert (nl.watchlist_name, nl.watchlist_version) == ("some_list", "v9")
    with pytest.raises(dataclasses.FrozenInstanceError):
        nl.watchlist_name = "x"  # type: ignore[misc]


@pytest.mark.parametrize("bad", ["", "  ", None])
def test_not_loaded_rejects_blank_identity(bad: Any) -> None:
    with pytest.raises(WatchlistValidationError):
        WatchlistVersionNotLoaded(bad, "v1")
    with pytest.raises(WatchlistValidationError):
        WatchlistVersionNotLoaded("list", bad)


def test_old_exception_class_is_gone_and_variant_is_exported() -> None:
    assert not hasattr(sanctions_errors, "WatchlistVersionNotLoaded")
    assert sanctions_pkg.WatchlistVersionNotLoaded is WatchlistVersionNotLoaded
    assert sanctions_pkg.LoadedWatchlistVersion is LoadedWatchlistVersion
    assert "WatchlistVersionNotLoaded" in sanctions_pkg.__all__
    assert "LoadedWatchlistVersion" in sanctions_pkg.__all__
    assert "WatchlistReadResult" in sanctions_pkg.__all__
    assert sanctions_pkg.WatchlistReadResult == WatchlistReadResult


# --------------------------------------------------------------------------
# Matcher: missing version can only yield NOT_PERFORMED(WATCHLIST_VERSION_NOT_LOADED)
# --------------------------------------------------------------------------


def _assert_only_version_abstention(res: Any, nl: WatchlistVersionNotLoaded) -> None:
    assert res.outcome == ScreeningOutcome.NOT_PERFORMED
    assert res.reason_code == AbstentionReason.WATCHLIST_VERSION_NOT_LOADED
    assert res.candidates == ()
    assert res.watchlist_name == nl.watchlist_name
    assert res.watchlist_version == nl.watchlist_version
    assert res.outcome != ScreeningOutcome.NO_CANDIDATE_MATCH
    assert res.outcome != ScreeningOutcome.CANDIDATE_MATCHES_FOUND


def test_matcher_missing_version_abstains_with_variant_identity() -> None:
    nl = WatchlistVersionNotLoaded("pinned_list", "v7")
    res = match_customer_against_watchlist("Aurelius Vance", None, nl)
    _assert_only_version_abstention(res, nl)


@pytest.mark.parametrize(
    "customer_name",
    [
        None,  # would otherwise be CUSTOMER_NAME_MISSING
        "",  # would otherwise be CUSTOMER_NAME_EMPTY_AFTER_NORMALIZATION
        "   ",
        "\u00a0",  # NBSP-only
        "\u3000",  # ideographic space only
        "Aurelius Vance",  # exact corpus primary
        "  Ａｕｒｅｌｉｕｓ    Ｖａｎｃｅ  ",  # fullwidth/whitespace variant
        "Kaz Drake",  # exact corpus alias
        "Zephyr Nightingale",  # unrelated
    ],
)
def test_matcher_missing_version_precedence_over_name_abstentions(
    customer_name: str | None,
) -> None:
    nl = WatchlistVersionNotLoaded(
        SYNTHETIC_WATCHLIST_NAME, SYNTHETIC_WATCHLIST_VERSION
    )
    for dob in (None, datetime.date(1980, 5, 15)):
        _assert_only_version_abstention(
            match_customer_against_watchlist(customer_name, dob, nl), nl
        )


def test_matcher_missing_version_property_over_all_known_names() -> None:
    """
    For every listed name in the corpus and every frozen evaluation-case
    customer name, a missing version yields only the version abstention.
    """
    nl = WatchlistVersionNotLoaded(
        SYNTHETIC_WATCHLIST_NAME, SYNTHETIC_WATCHLIST_VERSION
    )
    names: list[str | None] = [e.listed_name for e in SYNTHETIC_WATCHLIST_CORPUS]
    names += [c.customer_name for c in get_sanctions_eval_cases()]
    assert len(names) >= 10 + 8
    for name in names:
        _assert_only_version_abstention(
            match_customer_against_watchlist(name, None, nl), nl
        )


def test_matcher_rejects_legacy_tuple_input_without_echoing_it() -> None:
    legacy = (
        dataclasses.replace(_entries()[0], listed_name=CANARY),
        *_entries()[1:],
    )
    with pytest.raises(TypeError) as exc:
        match_customer_against_watchlist(
            "Aurelius Vance", None, legacy  # type: ignore[arg-type]
        )
    assert "Canary" not in str(exc.value)
    with pytest.raises(TypeError):
        match_customer_against_watchlist(
            "Aurelius Vance", None, None  # type: ignore[arg-type]
        )


# --------------------------------------------------------------------------
# Reader error text (database-free, via a stub connection)
# --------------------------------------------------------------------------


class _StubResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchall(self) -> list[Any]:
        return self._rows


class _StubConnection:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def execute(self, *_args: Any, **_kwargs: Any) -> _StubResult:
        return _StubResult(self._rows)


def test_reader_zero_rows_returns_variant_via_stub_connection() -> None:
    result = read_watchlist_version(_StubConnection([]), "list_a", "v1")  # type: ignore[arg-type]
    assert isinstance(result, WatchlistVersionNotLoaded)
    assert (result.watchlist_name, result.watchlist_version) == ("list_a", "v1")


def test_reader_malformed_row_error_text_never_echoes_row_data() -> None:
    row = SimpleNamespace(
        entry_id="00000000-0000-0000-0000-000000000001",
        watchlist_name="list_a",
        watchlist_version="v1",
        subject_key="SUBJ-CANARY",
        name_type=CANARY,  # invalid enum value carrying a canary
        listed_name=CANARY,
        date_of_birth=datetime.date(1971, 3, 9),
        is_synthetic=True,
        source="test",
        created_at=None,
    )
    with pytest.raises(WatchlistIntegrityViolation) as exc:
        read_watchlist_version(_StubConnection([row]), "list_a", "v1")  # type: ignore[arg-type]
    text = str(exc.value)
    assert text == "Malformed watchlist entry data."
    for secret in (CANARY, "Canary", "1971", "SUBJ-CANARY"):
        assert secret not in text


# --------------------------------------------------------------------------
# Baseline freeze
# --------------------------------------------------------------------------


def test_baseline_output_sha_is_frozen() -> None:
    """The contract change must not alter the documented baseline output."""
    output = canonical_json(measure_sanctions_baseline()) + "\n"
    assert hashlib.sha256(output.encode("utf-8")).hexdigest() == FROZEN_BASELINE_SHA256
    assert len(output.encode("utf-8")) == 15_730
