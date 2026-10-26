"""Safety boundaries around the combined evaluation entry point."""

import json
from unittest.mock import Mock

import pytest

from meridian.evaluation import run as evaluation


def test_database_guard_precedes_connections_or_mutations(monkeypatch):
    connection = Mock()
    mutation = Mock()
    guard = Mock(side_effect=RuntimeError("unsafe database"))
    monkeypatch.setattr(evaluation, "verify_test_database_safety", guard)
    monkeypatch.setattr(evaluation, "create_engine", connection)
    monkeypatch.setattr(evaluation, "clear_data", mutation)
    with pytest.raises(RuntimeError, match="unsafe database"):
        evaluation.run()
    connection.assert_not_called()
    mutation.assert_not_called()


def test_recorded_heldout_tampering_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluation, "EVALUATION_DIR", tmp_path)
    monkeypatch.setattr(evaluation, "validate_freeze", lambda: "approved")
    receipt = {
        "status": "COMPLETED",
        "frozen_sha256": "approved",
        "result_sha256": "wrong",
    }
    (tmp_path / "policy_retrieval_eval_v1.heldout-receipt.json").write_text(
        json.dumps(receipt)
    )
    (tmp_path / "policy_retrieval_eval_v1.heldout.json").write_text("{}")
    with pytest.raises(ValueError, match="does not match"):
        evaluation.recorded_policy()


def test_recorded_heldout_reused_without_new_measurement():
    result = evaluation.recorded_policy()
    assert result["status"] == "RECORDED_RESULT_REUSED"
    assert (
        result["sha256"]
        == "9432fd0ef67202770b7bcdb277429f0646dc8b775cbde7aa592c54492459e299"
    )
