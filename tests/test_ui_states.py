"""Streamlit renders authoritative states and bounded request failures."""

from typing import Any
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


def app() -> AppTest:
    at = AppTest.from_file("../ui/streamlit_app.py")
    at.session_state["api_token_input"] = "synthetic-test-token"
    at.session_state["active_case_id"] = "synthetic-case"
    return at.run()


def click(at: AppTest, label: str) -> None:
    if label == "Fetch Report" and at.session_state.get("view") != "Report":
        at.radio(key="view").set_value("Report").run()
    elif label == "Investigate" and at.session_state.get("view") != "Investigation":
        at.radio(key="view").set_value("Investigation").run()
    elif label == "Create Case" and at.session_state.get("view") != "Case Intake":
        at.radio(key="view").set_value("Case Intake").run()
    elif label == "Fetch Audit Trail" and at.session_state.get("view") != "Audit Trail":
        at.radio(key="view").set_value("Audit Trail").run()
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


def test_report_persists_across_rerun_and_audit_navigation() -> None:
    report_data = _report_payload(status="COMPLETE")
    response = Mock(status_code=200)
    response.json.return_value = report_data
    audit_data = {"investigation_runs": [], "audit_events": []}
    audit_response = Mock(status_code=200)
    audit_response.json.return_value = audit_data

    def fake_get(url: str, *args: Any, **kwargs: Any) -> Mock:
        if "/report" in url:
            return response
        elif "/copilot-draft" in url:
            copilot_mock = Mock(status_code=200)
            copilot_mock.json.return_value = {
                "case_id": "synthetic-case",
                "run_id": "11111111-1111-1111-1111-111111111111",
                "status": "UNAVAILABLE",
                "reason": "MOCK",
                "authoritative": False,
                "package_hash": "a" * 64,
                "prompt_version": "v1.0",
                "model_identifier": "deterministic-mock-v1",
                "limitations": [],
                "draft": None,
                "policy_provenance": None,
            }
            return copilot_mock
        elif "/audit-trail" in url:
            return audit_response
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        click(at, "Fetch Report")
        assert any(
            "Authoritative investigation report summary" in item.value
            for item in at.markdown
        )

        # Navigate to Audit Trail and fetch audit
        click(at, "Fetch Audit Trail")
        assert at.session_state["view"] == "Audit Trail"

        # Navigate back to Report view without clicking Fetch Report
        at.radio(key="view").set_value("Report").run()
        assert not at.exception
        # Report is rendered from session_state immediately
        assert any(
            "Authoritative investigation report summary" in item.value
            for item in at.markdown
        )


def test_no_candidate_match_has_no_success_styling() -> None:
    report_data = _report_payload(status="COMPLETE")
    report_data["watchlist_screening"] = {
        "state": "NO_CANDIDATE_MATCH",
        "rendered_text": (
            "Exact-name match: NO CANDIDATE MATCH. This is not a clearance."
        ),
    }
    response = Mock(status_code=200)
    response.json.return_value = report_data
    with patch("requests.get", return_value=response):
        at = app()
        click(at, "Fetch Report")
        assert not at.success
        assert any("NO_CANDIDATE_MATCH" in item.value for item in at.markdown)
        assert any(
            "No candidate does not mean clearance." in item.value
            for item in at.caption
        )


def test_prototype_notice_present_when_risk_signals_render() -> None:
    report_data = _report_payload(status="COMPLETE")
    report_data["risk_signals"] = [
        {
            "signal_type": "transaction_velocity",
            "value": 4.5,
            "methodology": "sql_deterministic",
            "transaction_id": "tx-123",
        }
    ]
    response = Mock(status_code=200)
    response.json.return_value = report_data
    with patch("requests.get", return_value=response):
        at = app()
        click(at, "Fetch Report")
        assert any(
            "PROTOTYPE — not a validated risk score or AML determination" in item.value
            for item in at.markdown
        )


def test_no_risk_score_widget_exists() -> None:
    report_data = _report_payload(status="COMPLETE")
    report_data["risk_signals"] = [
        {
            "signal_type": "transaction_velocity",
            "value": 4.5,
            "methodology": "sql_deterministic",
        }
    ]
    response = Mock(status_code=200)
    response.json.return_value = report_data
    with patch("requests.get", return_value=response):
        at = app()
        click(at, "Fetch Report")
        all_text = " ".join(
            item.value
            for item in list(at.markdown)
            + list(at.text)
            + [m.label + str(m.value) for m in at.metric]
        )
        assert "Risk Score" not in all_text
        assert "Composite Score" not in all_text


def test_session_progress_reflects_only_performed_actions() -> None:
    report_data = _report_payload(status="COMPLETE")
    response = Mock(status_code=200)
    response.json.return_value = report_data
    with patch("requests.get", return_value=response):
        at = app()
        initial_progress = " ".join(
            m.value for m in at.markdown if "This session:" in m.value
        )
        assert "○ Case Created" in initial_progress
        assert "○ Report Fetched" in initial_progress

        click(at, "Fetch Report")
        at.run()
        updated_progress = " ".join(
            m.value for m in at.markdown if "This session:" in m.value
        )
        assert "✓ Report Fetched" in updated_progress
        assert "○ Case Created" in updated_progress
        assert "○ Investigated" in updated_progress
        assert "○ Decision Submitted" in updated_progress


def test_unknown_status_renders_raw_without_guessing() -> None:
    report_data = _report_payload(status="FUTURE_UNKNOWN_STATUS_CODE")
    response = Mock(status_code=200)
    response.json.return_value = report_data
    with patch("requests.get", return_value=response):
        at = app()
        click(at, "Fetch Report")
        assert any("FUTURE_UNKNOWN_STATUS_CODE" in item.value for item in at.markdown)


def test_multi_case_session_isolation() -> None:
    report_a = _report_payload(status="COMPLETE")
    report_a["summary"] = "Case A Unique Summary"
    report_b = _report_payload(status="INCOMPLETE_INSUFFICIENT_EVIDENCE")
    report_b["summary"] = "Case B Different Summary"

    def fake_get(url: str, *args: Any, **kwargs: Any) -> Mock:
        if "/cases/case-a/report" in url:
            resp = Mock(status_code=200)
            resp.json.return_value = report_a
            return resp
        elif "/cases/case-b/report" in url:
            resp = Mock(status_code=200)
            resp.json.return_value = report_b
            return resp
        elif "/copilot-draft" in url:
            copilot_mock = Mock(status_code=200)
            copilot_mock.json.return_value = {
                "case_id": "synthetic-case",
                "run_id": "11111111-1111-1111-1111-111111111111",
                "status": "UNAVAILABLE",
                "reason": "MOCK",
                "authoritative": False,
                "package_hash": "a" * 64,
                "prompt_version": "v1.0",
                "model_identifier": "deterministic-mock-v1",
                "limitations": [],
                "draft": None,
                "policy_provenance": None,
            }
            return copilot_mock
        raise ValueError(f"Unexpected GET URL: {url}")

    with patch("requests.get", side_effect=fake_get):
        at = app()
        # 1. Case A has a populated report in session state
        at.text_input(key="active_case_id").set_value("case-a").run()
        click(at, "Fetch Report")
        assert any("Case A Unique Summary" in m.value for m in at.markdown)

        # 2. Switching to Case B does not display Case A's report
        at.text_input(key="active_case_id").set_value("case-b").run()
        assert not any("Case A Unique Summary" in m.value for m in at.markdown)
        assert any(
            "No report loaded for this case" in item.value for item in at.info
        )

        # 3. Case B can hold a different report
        click(at, "Fetch Report")
        assert any("Case B Different Summary" in m.value for m in at.markdown)
        assert not any("Case A Unique Summary" in m.value for m in at.markdown)

        # 4. Returning to Case A restores its original report
        at.text_input(key="active_case_id").set_value("case-a").run()
        assert any("Case A Unique Summary" in m.value for m in at.markdown)
        assert not any("Case B Different Summary" in m.value for m in at.markdown)

        # 5. Neither case's cached data is overwritten or mixed
        at.text_input(key="active_case_id").set_value("case-b").run()
        assert any("Case B Different Summary" in m.value for m in at.markdown)
        assert not any("Case A Unique Summary" in m.value for m in at.markdown)
