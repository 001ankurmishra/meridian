"""Streamlit renders authoritative states and bounded request failures."""

from unittest.mock import Mock, patch

import pytest
import requests
from streamlit.testing.v1 import AppTest

STATES = [
    "CANDIDATE_MATCHES_FOUND",
    "NO_CANDIDATE_MATCH",
    "NOT_PERFORMED",
    "SCREENING_ERROR",
    "INCONSISTENT_MISSING_RESULT",
    "SCREENING_NOT_RECORDED",
    "INCONSISTENT_INVALID_ROW",
]


def app():
    at = AppTest.from_file("../ui/streamlit_app.py")
    at.session_state["api_token_input"] = "synthetic-test-token"
    at.session_state["active_case_id"] = "synthetic-case"
    return at.run()


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception


@pytest.mark.parametrize("state", STATES)
def test_screening_uses_authoritative_rendered_text(state):
    rendered = f"Authoritative screening text for {state}. Not determined."
    response = Mock(status_code=200)
    response.json.return_value = {
        "summary": "Synthetic report",
        "evidence_completeness_status": "INCOMPLETE",
        "confidence_text": "Insufficient evidence",
        "watchlist_screening": {
            "state": state,
            "rendered_text": rendered,
        },
    }
    with patch("requests.get", return_value=response) as get:
        at = app()
        click(at, "Fetch Report")
        assert any(rendered in item.value for item in at.markdown)
        assert any(state in item.value for item in at.text)
        assert get.call_args.kwargs["timeout"] == (5, 60)
        assert any("does not establish" in item.value for item in at.warning)


@pytest.mark.parametrize("status", ["COMPLETE", "INCOMPLETE", "FAILED", "IN_PROGRESS"])
def test_only_complete_investigation_shows_success(status):
    response = Mock(status_code=200)
    response.json.return_value = {"status": status}
    with patch("requests.post", return_value=response) as post:
        at = app()
        click(at, "Investigate")
        assert bool(at.success) is (status == "COMPLETE")
        assert post.call_args.kwargs["timeout"] == (5, 120)


def test_timeout_does_not_echo_exception_or_claim_failure_of_operation():
    with patch("requests.post", side_effect=requests.Timeout("private-token-canary")):
        at = app()
        click(at, "Investigate")
        visible = " ".join(item.value for item in list(at.error) + list(at.info))
        assert "private-token-canary" not in visible
        assert "may still finish" in visible
        assert not at.success
