"""Versioned mock-transport readiness run; no live entry point or model accuracy."""

import argparse
import asyncio
import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx

from meridian.copilot.budget import BudgetLedger
from meridian.copilot.explanations import (
    EXPLANATION_PROMPT,
    EXPLANATION_VERSION,
    assess_explanation,
    explanation_schema,
)
from meridian.copilot.openai_pilot import MODEL, OpenAIPilot, PilotError
from meridian.copilot.synthetic import FIXTURE_SHA256, fixtures, synthetic_package

MOCK_PILOT_ID = "v5b-mock-review-v1"


def proposed_output(item: dict[str, str]) -> str:
    package = synthetic_package(item["id"])
    claims = []
    if package.passages and item["mocked_claim"]:
        p = package.passages[0]
        claims.append(
            {
                "passage_id": p.passage_id,
                "kind": p.kind,
                "text": item["mocked_claim"],
                "evidence_ids": list(p.evidence_ids),
            }
        )
    if item["id"] == "fabricated_citation":
        claims[0]["evidence_ids"] = ["00000000-0000-0000-0000-000000000099"]
    return json.dumps(
        {
            "package_hash": "0" * 64
            if item["id"] == "cross_investigation"
            else package.package_hash,
            "status": "DRAFT" if claims else "ABSTAIN",
            "claims": claims,
            "limitations": []
            if item["id"] == "omission"
            else list(package.limitations),
        }
    )


async def run_mock_suite(ledger_path: Path) -> dict[str, Any]:
    ledger = BudgetLedger(ledger_path, pilot_id=MOCK_PILOT_ID)
    if ledger.snapshot()["requests"]:
        raise ValueError("USE_NEW_BENCHMARK_LEDGER")
    records = []
    for item in fixtures():

        async def handler(request: httpx.Request) -> httpx.Response:
            if item["id"] == "timeout":
                await asyncio.sleep(60)
            if item["id"] == "provider_failure":
                return httpx.Response(503, text="synthetic provider failure")
            return httpx.Response(
                200,
                json={
                    "model": MODEL,
                    "status": "completed",
                    "usage": {
                        "input_tokens": 1000,
                        "output_tokens": 100,
                        "total_tokens": 1100,
                        "output_tokens_details": {"reasoning_tokens": 20},
                    },
                    "output": [
                        {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": proposed_output(item)}
                            ],
                        }
                    ],
                },
            )

        adapter = OpenAIPilot(
            ledger,
            mock_transport=httpx.MockTransport(handler),
            experimental=True,
            timeout_seconds=0.05,
        )
        start = time.monotonic()
        record: dict[str, Any] = {
            "fixture_id": item["id"],
            "schema_compliance": None,
            "citation_validity": None,
            "numeric_fidelity": None,
            "semantic_claim_support": None,
            "appropriate_abstention": None,
            "unsupported_claim_rate": None,
            "independent_reviewer": None,
            "actual_token_usage": None,
            "actual_api_cost_usd": None,
        }
        try:
            raw = await adapter.generate_structured(
                EXPLANATION_PROMPT,
                synthetic_package(item["id"]).payload(),
                explanation_schema(),
            )
            assessment = assess_explanation(
                raw, synthetic_package(item["id"]), enabled=True
            )
            record.update(
                schema_compliance=assessment.schema_compliant,
                citation_validity=assessment.citations_valid,
                numeric_fidelity=assessment.numeric_fidelity,
                assessment=asdict(assessment),
            )
            category = (
                "abstain"
                if assessment.status == "ABSTAIN"
                else "review"
                if assessment.reason == "SEMANTIC_REVIEW_REQUIRED"
                else "reject"
            )
        except PilotError as exc:
            category = "timeout" if str(exc) == "TIMEOUT" else "failure"
            record["provider_outcome"] = category
        record.update(
            latency_seconds=time.monotonic() - start,
            expected_mechanical=item["expected_mechanical"],
            mechanical_outcome=category,
        )
        records.append(record)
    return {
        "mode": "MOCK_TRANSPORT_ONLY",
        "model_requested": MODEL,
        "model_executed": None,
        "prompt_version": EXPLANATION_VERSION,
        "fixture_sha256": FIXTURE_SHA256,
        "live_requests": 0,
        "semantic_faithfulness": "NOT_MEASURED",
        "records": records,
        "mock_accounting": ledger.snapshot(),
        "expectations_met": sum(
            r["mechanical_outcome"] == r["expected_mechanical"] for r in records
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    # Claim output path first, so reruns never overwrite recorded evidence.
    with args.output.open("x") as stream:
        result = asyncio.run(run_mock_suite(args.ledger))
        result["source_hashes"] = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [Path(__file__), *Path("src/meridian/copilot").glob("*.py")]
        }
        stream.write(json.dumps(result, indent=2) + "\n")
