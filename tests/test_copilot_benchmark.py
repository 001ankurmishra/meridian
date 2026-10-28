from decimal import Decimal
from pathlib import Path

import pytest

from meridian.evaluation.copilot import estimate_cost, measure

pytestmark = pytest.mark.offline_guard_unit


def test_versioned_mechanical_benchmark(tmp_path):
    result = measure(
        Path("docs/evaluation/v5/benchmark-v1.json"), tmp_path / "run.json"
    )
    assert result["mechanical_expectations_met"] == result["examples"] == 14
    assert result["semantic_faithfulness"] == "NOT_MEASURED"
    assert result["input_tokens"] is None
    with pytest.raises(FileExistsError):
        measure(Path("docs/evaluation/v5/benchmark-v1.json"), tmp_path / "run.json")


def test_cost_uses_billable_tokens_without_fabricating_usage():
    assert estimate_cost(4000, 1000, Decimal(".75"), Decimal("4.50")) == Decimal(
        ".0075"
    )
    with pytest.raises(ValueError):
        estimate_cost(-1, 0, Decimal("1"), Decimal("1"))
