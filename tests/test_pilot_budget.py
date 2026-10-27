from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from meridian.copilot.budget import RESERVATION, BudgetError, BudgetLedger, micro_cost

pytestmark = pytest.mark.offline_guard_unit


def attempt(path):
    try:
        BudgetLedger(Path(path), max_requests=5).reserve("synthetic", "v1")
        return True
    except BudgetError:
        return False


def test_concurrent_reservations_across_threads_and_processes(tmp_path):
    path = tmp_path / "budget.json"
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(attempt, [str(path)] * 20)) == 5
    # Fresh path, independent processes use the same stable lock inode.
    path = tmp_path / "process.json"
    with ProcessPoolExecutor(3) as pool:
        assert sum(pool.map(attempt, [str(path)] * 12)) == 5
    assert len(BudgetLedger(path, max_requests=5).snapshot()["requests"]) == 5


def test_insufficient_budget_and_crash_reservation_survive_restart(tmp_path):
    path = tmp_path / "ledger.json"
    ledger = BudgetLedger(path, max_micro_usd=RESERVATION)
    rid = ledger.reserve("x", "v1")
    restarted = BudgetLedger(path, max_micro_usd=RESERVATION)
    assert restarted.snapshot()["requests"][rid]["state"] == "PENDING"
    with pytest.raises(BudgetError, match="PILOT_LIMIT_REACHED"):
        restarted.reserve("x", "v1")
    restarted.reconcile(rid, None, "TIMEOUT", 0.1)
    assert restarted.snapshot()["requests"][rid]["charged_micro_usd"] == RESERVATION
    with pytest.raises(BudgetError):
        restarted.reconcile(rid, None, "again", 0.1)


def test_usage_includes_reasoning_once_and_releases_unused_reservation(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json")
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
    ledger = BudgetLedger(tmp_path / "ledger.json")
    rid = ledger.reserve("x", "v1")
    ledger.reconcile(rid, usage, "UNKNOWN", 0.1)
    row = ledger.snapshot()["requests"][rid]
    assert row["state"] == "UNKNOWN" and row["charged_micro_usd"] == RESERVATION


def test_reported_overage_halts_pilot_and_never_clamps_actual_cost(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json")
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
        BudgetLedger(path, max_requests=101)
    ledger = BudgetLedger(path)
    ledger.reserve("x", "v1")
    with pytest.raises(BudgetError):
        BudgetLedger(path, max_requests=99).reserve("x", "v1")
    path.write_text("not json")
    with pytest.raises(BudgetError):
        ledger.reserve("x", "v1")
