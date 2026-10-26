"""Verify a seeded local synthetic demo through the authenticated HTTP API.

Creates one worked-example case and records a synthetic APPROVE decision.
Supply a short-lived senior analyst token through MERIDIAN_DEMO_TOKEN.
"""

import argparse
import json
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from meridian.loader.worked_example import generate_worked_example


def verify(base_url: str, token: str) -> dict[str, Any]:
    if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Demo verification is restricted to a local deployment.")
    fixture = generate_worked_example()
    customer = uuid.uuid5(uuid.NAMESPACE_OID, "rahul_sharma")
    account = uuid.uuid5(uuid.NAMESPACE_OID, "rahul_acct_1")
    transaction = next(
        row["transaction_id"]
        for row in fixture["transactions"]
        if row["source_account_id"] == account and row["amount"] == 980000
    )
    headers = {"Authorization": f"Bearer {token}"}

    def call(method: str, path: str, expected: int = 200, **kwargs: Any) -> Any:
        response = requests.request(
            method,
            base_url.rstrip("/") + path,
            headers=headers,
            timeout=(5, 120),
            **kwargs,
        )
        if response.status_code != expected:
            raise RuntimeError(f"Demo {method} {path}: HTTP {response.status_code}")
        return response.json()

    call("GET", "/health")
    anonymous = requests.get(
        base_url + "/cases/" + str(uuid.uuid4()) + "/report", timeout=(5, 10)
    )
    assert anonymous.status_code == 401
    payload = {
        "customer_id": str(customer),
        "transaction_id": str(transaction),
        "alert_type": "large_transaction",
        "alert_reasons": {"synthetic_demo": True},
        "source_system": "phase-b-demo",
    }
    call(
        "POST",
        "/cases",
        expected=422,
        json={**payload, "actor_user_id": str(uuid.uuid4())},
    )
    case = call("POST", "/cases", expected=201, json=payload)
    path = "/cases/" + case["case_id"]
    investigation = call("POST", path + "/investigate")
    assert investigation["status"] == "COMPLETE"
    report = call("GET", path + "/report")
    assert report["is_synthetic"] and report["human_review_required"]
    assert report["findings"] and report["evidence"] and report["recommendations"]
    assert report["applicable_policies"]
    evidence_ids = {
        e["evidence_id"] for e in report["evidence"] + report["applicable_policies"]
    }
    finding_ids = {f["finding_id"] for f in report["findings"]}
    for finding in report["findings"]:
        assert finding["evidence_ids"]
        assert set(finding["evidence_ids"]).issubset(evidence_ids)
    for recommendation in report["recommendations"]:
        assert recommendation["based_on_finding_ids"]
        assert set(recommendation["based_on_finding_ids"]).issubset(finding_ids)
    screening = report["watchlist_screening"]
    assert screening["state"] == "NO_CANDIDATE_MATCH"
    assert screening["watchlist_version"] == "v1"
    assert screening["rendered_text"]
    call(
        "POST",
        path + "/decision",
        expected=422,
        json={"action": "APPROVE", "actor_user_id": str(uuid.uuid4())},
    )
    decision = call(
        "POST",
        path + "/decision",
        json={"action": "APPROVE", "reason": "Synthetic deployment verification only."},
    )
    assert decision["new_status"] == "CLOSED_APPROVED"
    audit = call("GET", path + "/audit-trail")
    assert audit["case_status"] == "CLOSED_APPROVED"
    run = next(
        r
        for r in audit["investigation_runs"]
        if r["investigation_run_id"] == report["investigation_run_id"]
    )
    assert run["status"] == "COMPLETE"
    assert evidence_ids.issubset({e["evidence_id"] for e in run["evidence"]})
    assert run["screening_result"]["outcome"] == "NO_CANDIDATE_MATCH"
    approvals = [e for e in audit["audit_events"] if e["action"] == "CASE_APPROVED"]
    assert len(approvals) == 1
    assert approvals[0]["actor_id"] == str(
        uuid.uuid5(uuid.NAMESPACE_OID, "dev_senior_analyst_1")
    )
    return {
        "status": "VERIFIED",
        "synthetic_only": True,
        "case_id": case["case_id"],
        "investigation_run_id": report["investigation_run_id"],
        "investigation_status": investigation["status"],
        "findings": len(finding_ids),
        "evidence": len(evidence_ids),
        "recommendations": len(report["recommendations"]),
        "policy_citations": len(report["applicable_policies"]),
        "screening_state": screening["state"],
        "watchlist_version": "v1",
        "decision_status": decision["new_status"],
        "audit_approval_events": 1,
        "unauthenticated_rejected": True,
        "actor_spoofing_rejected": True,
        "human_comparison": "NOT PERFORMED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite demonstration evidence.")
    result = verify(args.base_url, os.environ["MERIDIAN_DEMO_TOKEN"])
    with args.output.open("x") as file:
        json.dump(result, file, indent=2)
        file.write("\n")
    print("Synthetic deployment workflow verified; evidence saved.")


if __name__ == "__main__":
    main()
