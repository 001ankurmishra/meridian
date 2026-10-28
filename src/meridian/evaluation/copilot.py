"""Offline mechanical benchmark. No model call or semantic accuracy inference."""

import argparse
import hashlib
import json
import time
from decimal import Decimal
from pathlib import Path

from meridian.copilot.drafts import (
    PROMPT_VERSION,
    EvidencePackage,
    Passage,
    validate_draft,
)


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    input_usd_per_million: Decimal,
    output_usd_per_million: Decimal,
) -> Decimal:
    """Billable totals, including reasoning if applicable; no guessed token usage."""
    if (
        input_tokens < 0
        or output_tokens < 0
        or not input_usd_per_million.is_finite()
        or not output_usd_per_million.is_finite()
        or input_usd_per_million < 0
        or output_usd_per_million < 0
    ):
        raise ValueError("Invalid usage/rate")
    return (
        input_tokens * input_usd_per_million + output_tokens * output_usd_per_million
    ) / Decimal(1_000_000)


def measure(fixture_path: Path, output: Path) -> dict[str, object]:
    raw = fixture_path.read_bytes()
    fixture_hash = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw)
    observations = []
    for item in data["examples"]:
        source = Passage(
            item["id"],
            "observed_fact",
            item["source"],
            ("00000000-0000-0000-0000-000000000003",),
            ("00000000-0000-0000-0000-000000000004",),
            "LOW",
        )
        package = EvidencePackage(
            "synthetic-case",
            "synthetic-run",
            "COMPLETE",
            (source,),
            ("Semantic review pending",),
            fixture_hash,
        )
        claim = {
            "passage_id": source.passage_id,
            "kind": "observed_fact",
            "text": item["claim"],
            "evidence_ids": list(source.evidence_ids),
        }
        if item.get("foreign_citation"):
            claim["evidence_ids"] = ["00000000-0000-0000-0000-000000000099"]
        payload = {
            "package_hash": fixture_hash,
            "status": "ABSTAIN" if item.get("abstain") else "DRAFT",
            "summary": [] if item.get("abstain") else [claim],
            "explanations": [],
            "uncertainty": "INSUFFICIENT_SUPPORT"
            if item.get("abstain")
            else "RECORDED_EVIDENCE_ONLY",
        }
        begin = time.monotonic()
        try:
            validate_draft(json.dumps(payload), package)
            accepted = True
        except ValueError:
            accepted = False
        observations.append(
            {
                "id": item["id"],
                "accepted": accepted,
                "expected": item["mechanical_accept"],
                "latency_seconds": time.monotonic() - begin,
                "semantic_reviewer": None,
                "semantic_verdict": None,
            }
        )
    result = {
        "benchmark_version": data["version"],
        "fixture_sha256": fixture_hash,
        "prompt_version": PROMPT_VERSION,
        "model_identifier": "NO_MODEL",
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "validator_sha256": hashlib.sha256(
            Path("src/meridian/copilot/drafts.py").read_bytes()
        ).hexdigest(),
        "mechanical_expectations_met": sum(
            o["accepted"] == o["expected"] for o in observations
        ),
        "examples": len(observations),
        "observations": observations,
        "input_tokens": None,
        "output_tokens": None,
        "estimated_api_cost_usd": None,
        "actual_api_calls": 0,
        "semantic_faithfulness": "NOT_MEASURED",
        "independent_review": "PENDING",
    }
    with output.open("x") as stream:
        stream.write(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    measure(args.fixture, args.output)
