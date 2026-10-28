from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from meridian.copilot.budget import RESERVATION, BudgetError, BudgetLedger, micro_cost

pytestmark = pytest.mark.offline_guard_unit


def budget_ledger(path, **kwargs):
    return BudgetLedger(path, pilot_id="test-pilot", **kwargs)


def attempt(path):
    try:
        ledger = budget_ledger(Path(path), max_requests=5)
        ledger.reserve("synthetic", "v1")
        return True
    except BudgetError:
        return False


def test_concurrent_reservations_across_threads_and_processes(tmp_path):
    path = tmp_path / "budget.json"
    budget_ledger(path, max_requests=5).initialize()
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(attempt, [str(path)] * 20)) == 5
    # Fresh path, independent processes use the same stable lock inode.
    path = tmp_path / "process.json"
    budget_ledger(path, max_requests=5).initialize()
    with ProcessPoolExecutor(3) as pool:
        assert sum(pool.map(attempt, [str(path)] * 12)) == 5
    assert len(budget_ledger(path, max_requests=5).snapshot()["requests"]) == 5


def test_insufficient_budget_and_crash_reservation_survive_restart(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = budget_ledger(path, max_micro_usd=RESERVATION)
    ledger.initialize()
    rid = ledger.reserve("x", "v1")
    restarted = budget_ledger(path, max_micro_usd=RESERVATION)
    assert restarted.snapshot()["requests"][rid]["state"] == "PENDING"
    with pytest.raises(BudgetError, match="PILOT_LIMIT_REACHED"):
        restarted.reserve("x", "v1")
    restarted.reconcile(rid, None, "TIMEOUT", 0.1)
    assert restarted.snapshot()["requests"][rid]["charged_micro_usd"] == RESERVATION
    with pytest.raises(BudgetError):
        restarted.reconcile(rid, None, "again", 0.1)


def test_usage_includes_reasoning_once_and_releases_unused_reservation(tmp_path):
    ledger = budget_ledger(tmp_path / "ledger.json")
    ledger.initialize()
    rid = ledger.reserve("x", "v1")
    ledger.reconcile(
        rid,
        {
            "input_tokens": 4000,
            "output_tokens": 1000,
            "total_tokens": 5000,
            "output_tokens_details": {"reasoning_tokens": 400},
        },
        "RECEIVED",
        0.1,
    )
    row = ledger.snapshot()["requests"][rid]
    assert row["charged_micro_usd"] == 7500 == micro_cost(4000, 1000)
    assert row["usage"]["reasoning_tokens"] == 400


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"input_tokens": -1},
        {"input_tokens": True, "output_tokens": 2, "total_tokens": 3},
        {"input_tokens": 2, "output_tokens": 3, "total_tokens": 6},
        {
            "input_tokens": 2,
            "output_tokens": 3,
            "total_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 9},
        },
    ],
)
def test_unknown_or_malformed_usage_retains_full_reservation(tmp_path, usage):
    ledger = budget_ledger(tmp_path / "ledger.json")
    ledger.initialize()
    rid = ledger.reserve("x", "v1")
    ledger.reconcile(rid, usage, "UNKNOWN", 0.1)
    row = ledger.snapshot()["requests"][rid]
    assert row["state"] == "UNKNOWN" and row["charged_micro_usd"] == RESERVATION


def test_reported_overage_halts_pilot_and_never_clamps_actual_cost(tmp_path):
    ledger = budget_ledger(tmp_path / "ledger.json")
    ledger.initialize()
    rid = ledger.reserve("x", "v1")
    ledger.reconcile(
        rid,
        {"input_tokens": 9000, "output_tokens": 3000, "total_tokens": 12000},
        "RECEIVED",
        0.1,
    )
    assert ledger.snapshot()["halted"]
    assert ledger.snapshot()["requests"][rid]["charged_micro_usd"] > RESERVATION
    with pytest.raises(BudgetError):
        ledger.reserve("x", "v1")


def test_limits_corruption_and_configuration_changes_fail_closed(tmp_path):
    path = tmp_path / "ledger.json"
    with pytest.raises(BudgetError):
        budget_ledger(path, max_requests=101)
    ledger = budget_ledger(path)
    ledger.initialize()
    ledger.reserve("x", "v1")
    with pytest.raises(BudgetError):
        budget_ledger(path, max_requests=99).reserve("x", "v1")
    path.write_text("not json")
    with pytest.raises(BudgetError):
        ledger.reserve("x", "v1")


def test_missing_ledger_or_lock_never_resets_budget_state(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = budget_ledger(path)
    with pytest.raises(BudgetError, match="LEDGER_MISSING_OR_UNINITIALIZED"):
        ledger.reserve("x", "v1")
    ledger.initialize()
    assert ledger.initialization_record_path.exists()
    ledger.reserve("x", "v1")
    ledger.initialize()
    assert len(ledger.snapshot()["requests"]) == 1
    path.unlink()
    with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
        ledger.initialize()
    with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
        ledger.reserve("x", "v1")
    with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
        ledger.snapshot()
    assert not path.exists()
    assert path.with_suffix(".json.lock").exists()

    lock_path = tmp_path / "lock-missing.json"
    lock_ledger = budget_ledger(lock_path)
    lock_ledger.initialize()
    lock_ledger.reserve("x", "v1")
    lock_file = lock_path.with_suffix(lock_path.suffix + ".lock")
    lock_file.unlink()
    with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
        lock_ledger.reserve("x", "v1")
    with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
        lock_ledger.initialize()
    assert not lock_file.exists()


def test_both_accounting_files_lost_is_detected_by_pilot_bound_record(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = budget_ledger(path)
    ledger.initialize()
    ledger.reserve("synthetic", "v1")
    lock_path = path.with_suffix(path.suffix + ".lock")
    path.unlink()
    lock_path.unlink()

    for operation in (ledger.initialize, ledger.snapshot):
        with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
            operation()
    with pytest.raises(BudgetError, match="LEDGER_ACCOUNTING_STATE_LOST"):
        ledger.reserve("synthetic", "v1")
    assert ledger.initialization_record_path.exists()
    assert not path.exists() and not lock_path.exists()


def test_initialization_record_binds_pilot_and_cannot_be_recreated(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = budget_ledger(path)
    ledger.initialize()
    with pytest.raises(BudgetError, match="LEDGER_INITIALIZATION_RECORD_MISMATCH"):
        BudgetLedger(path, pilot_id="different-approved-pilot").snapshot()

    ledger.initialization_record_path.unlink()
    with pytest.raises(BudgetError, match="LEDGER_INITIALIZATION_RECORD_MISSING"):
        ledger.snapshot()
    with pytest.raises(BudgetError, match="LEDGER_INITIALIZATION_STATE_INCOMPLETE"):
        ledger.initialize()
