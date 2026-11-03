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
        "evidence_completeness_status": "INCOMPLETE_INSUFFICIENT_EVIDENCE",
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


@pytest.mark.parametrize(
    "status", ["COMPLETE", "INCOMPLETE_INSUFFICIENT_EVIDENCE", "FAILED", "IN_PROGRESS"]
)
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


def test_seeded_demo_defaults_and_guidance():
    import uuid

    from meridian.loader.worked_example import generate_worked_example

    at = app()
    fields = {item.label: item.value for item in at.text_input}
    assert fields["Alert Type"] == "large_transaction"
    tx = fields["Transaction ID (UUID; needed for transaction evidence)"]
    fixture = generate_worked_example()
    assert uuid.UUID(tx) in {row["transaction_id"] for row in fixture["transactions"]}
    assert any("assigned analyst" in item.value for item in at.info)
    assert any("First demo" in item.value for item in at.info)


def test_missing_transaction_is_explicitly_incomplete():
    response = Mock(status_code=201)
    response.json.return_value = {"case_id": "synthetic-case", "alert_id": "alert"}
    with patch("requests.post", return_value=response) as post:
        at = app()
        field = next(
            item for item in at.text_input if item.label.startswith("Transaction ID")
        )
        field.set_value("")
        click(at, "Create Case")
        assert "transaction_id" not in post.call_args.kwargs["json"]
        assert any(
            "transaction evidence will be missing" in item.value for item in at.warning
        )


def test_backend_incomplete_code_has_specific_guidance():
    response = Mock(status_code=200)
    response.json.return_value = {"status": "INCOMPLETE_INSUFFICIENT_EVIDENCE"}
    with patch("requests.post", return_value=response):
        at = app()
        click(at, "Investigate")
        assert any("Review missing evidence" in item.value for item in at.warning)
        assert not at.success


def _report_payload(status="COMPLETE", run_id="11111111-1111-1111-1111-111111111111"):
    return {
        "summary": "Authoritative investigation report summary",
        "evidence_completeness_status": status,
        "confidence_text": "High confidence",
        "investigation_run_id": run_id,
        "watchlist_screening": {
            "state": "NO_CANDIDATE_MATCH",
            "rendered_text": "No candidate matches found.",
        },
        "findings": [],
        "recommendations": [{"text": "Approve transaction"}],
        "evidence": [],
        "applicable_policies": [],
    }


def test_copilot_draft_renders_successful_draft():
    run_id = "11111111-1111-1111-1111-111111111111"
    pkg_hash = "a" * 64
    report_data = _report_payload(status="COMPLETE", run_id=run_id)
    draft_response_data = {
        "case_id": "synthetic-case",
        "run_id": run_id,
        "status": "DRAFT",
        "reason": "EXTRACTIVE_ONLY",
        "authoritative": False,
        "package_hash": pkg_hash,
        "prompt_version": "v1.0",
        "model_identifier": "deterministic-mock-v1",
        "limitations": ["EXTRACTIVE_ONLY", "NO_SEMANTIC_REASONING"],
        "draft": {
            "package_hash": pkg_hash,
            "status": "DRAFT",
            "summary": [
                {
                    "passage_id": "f1:observed_fact",
                    "kind": "observed_fact",
                    "text": "Transaction amount is INR 980,000.",
                    "evidence_ids": ["ev-1", "ev-2"],
                }
            ],
            "explanations": [
                {
                    "passage_id": "f2:derived_signal",
                    "kind": "derived_signal",
                    "text": "Transaction is 5x customer average.",
                    "evidence_ids": ["ev-3"],
                }
            ],
            "uncertainty": "RECORDED_EVIDENCE_ONLY",
        },
        "policy_provenance": {
            "registry_version": "2026.1",
            "registry_hash": "b" * 64,
            "chunks": [
                {
                    "chunk_id": "pol-chunk-1",
                    "document_title": "AML Transaction Monitoring Policy",
                }
            ],
        },
    }

    def fake_get(url, *args, **kwargs):
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            assert kwargs.get("timeout") == (5, 60)
            assert "Authorization" in kwargs.get("headers", {})
            m = Mock(status_code=200)
            m.json.return_value = draft_response_data
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        # Authoritative report preserved
        assert any(
            "Authoritative investigation report summary" in item.value
            for item in at.markdown
        )
        assert any("Approve transaction" in item.value for item in at.markdown)

        # Copilot non-authoritative warning present
        assert any(
            "NON-AUTHORITATIVE SUPPLEMENTARY DRAFT" in item.value for item in at.warning
        )

        # Metadata displayed
        assert any("deterministic-mock-v1" in item.value for item in at.caption)
        assert any(pkg_hash in item.value for item in at.caption)

        # Draft claims displayed
        assert any(
            "Transaction amount is INR 980,000." in item.value for item in at.markdown
        )
        assert any(
            "Transaction is 5x customer average." in item.value for item in at.markdown
        )

        # Policy provenance displayed
        assert any(
            "AML Transaction Monitoring Policy" in item.value for item in at.markdown
        )

        # Limitations displayed
        assert any("EXTRACTIVE_ONLY" in item.value for item in at.markdown)


def test_copilot_draft_abstention_renders_honestly():
    run_id = "22222222-2222-2222-2222-222222222222"
    pkg_hash = "c" * 64
    report_data = _report_payload(
        status="INCOMPLETE_INSUFFICIENT_EVIDENCE", run_id=run_id
    )
    draft_response_data = {
        "case_id": "synthetic-case",
        "run_id": run_id,
        "status": "ABSTAIN",
        "reason": "INSUFFICIENT_SUPPORT",
        "authoritative": False,
        "package_hash": pkg_hash,
        "prompt_version": "v1.0",
        "model_identifier": "deterministic-mock-v1",
        "limitations": ["INSUFFICIENT_SUPPORT"],
        "draft": None,
        "policy_provenance": None,
    }

    def fake_get(url, *args, **kwargs):
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            m = Mock(status_code=200)
            m.json.return_value = draft_response_data
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        # Authoritative report preserved
        assert any(
            "Authoritative investigation report summary" in item.value
            for item in at.markdown
        )

        # Prominent warning present
        assert any(
            "NON-AUTHORITATIVE SUPPLEMENTARY DRAFT" in item.value for item in at.warning
        )

        # Explicit abstention banner with reason and no substantive claims
        assert any(
            "Copilot Abstained: INSUFFICIENT_SUPPORT — "
            "No substantive claims were generated." in item.value
            for item in at.info
        )
        assert not any("Draft Summary Claims" in item.value for item in at.markdown)
        assert any(pkg_hash in item.value for item in at.caption)
        assert any("INSUFFICIENT_SUPPORT" in item.value for item in at.markdown)


def test_copilot_draft_not_called_for_ineligible_run_status():
    report_data = _report_payload(
        status="IN_PROGRESS", run_id="33333333-3333-3333-3333-333333333333"
    )
    draft_endpoint_called = False

    def fake_get(url, *args, **kwargs):
        nonlocal draft_endpoint_called
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            draft_endpoint_called = True
            m = Mock(status_code=200)
            m.json.return_value = {}
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        assert not draft_endpoint_called
        assert any(
            "Copilot draft is unavailable because the investigation run "
            "is not in a completed or evaluated terminal state." in item.value
            for item in at.info
        )


def test_copilot_draft_not_called_if_missing_run_id():
    report_data = _report_payload(status="COMPLETE", run_id=None)
    draft_endpoint_called = False

    def fake_get(url, *args, **kwargs):
        nonlocal draft_endpoint_called
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            draft_endpoint_called = True
            m = Mock(status_code=200)
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        assert not draft_endpoint_called
        assert any(
            "Copilot draft is unavailable because the investigation run "
            "is not in a completed or evaluated terminal state." in item.value
            for item in at.info
        )


def test_copilot_draft_unavailable_status_rendered_safely():
    report_data = _report_payload(
        status="COMPLETE", run_id="44444444-4444-4444-4444-444444444444"
    )
    draft_response_data = {
        "case_id": "synthetic-case",
        "run_id": "44444444-4444-4444-4444-444444444444",
        "status": "UNAVAILABLE",
        "reason": "TIMEOUT",
        "authoritative": False,
        "package_hash": "d" * 64,
        "prompt_version": "v1.0",
        "model_identifier": "deterministic-mock-v1",
        "limitations": [],
        "draft": None,
        "policy_provenance": None,
    }

    def fake_get(url, *args, **kwargs):
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            m = Mock(status_code=200)
            m.json.return_value = draft_response_data
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        assert any(
            "Copilot draft unavailable: TIMEOUT" in item.value for item in at.warning
        )
        assert not at.exception


def test_copilot_draft_http_503_error_handled_gracefully():
    report_data = _report_payload(
        status="COMPLETE", run_id="55555555-5555-5555-5555-555555555555"
    )

    def fake_get(url, *args, **kwargs):
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            m = Mock(status_code=503)
            m.headers = {}
            return m
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        # Report still intact
        assert any(
            "Authoritative investigation report summary" in item.value
            for item in at.markdown
        )
        # Safe failure message rendered
        assert any(
            "Copilot draft retrieval could not be completed (HTTP 503)" in item.value
            for item in at.error
        )
        assert not at.exception


def test_copilot_draft_network_timeout_handled_gracefully():
    report_data = _report_payload(
        status="COMPLETE", run_id="66666666-6666-6666-6666-666666666666"
    )

    def fake_get(url, *args, **kwargs):
        if "/report" in url:
            m = Mock(status_code=200)
            m.json.return_value = report_data
            return m
        elif "/copilot-draft" in url:
            raise requests.Timeout("network-canary-secret")
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")

        visible = " ".join(item.value for item in list(at.error) + list(at.info))
        assert "network-canary-secret" not in visible
        assert "The API did not respond within the request limits" in visible
        assert not at.exception
