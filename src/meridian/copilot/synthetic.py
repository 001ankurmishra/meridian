"""Fixed synthetic-only registry; never accept arbitrary 'is_synthetic' flags."""

import hashlib
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from meridian.copilot.drafts import EvidencePackage, Passage

FIXTURE_PATH = (
    Path(__file__).resolve().parents[3] / "docs/evaluation/v5b/fixtures-v1.json"
)
FIXTURE_SHA256 = "fef685e128774c7c6eb0c4d11731101f18a1cca94fcd9bbf3e90bb53d7c487bd"


def fixtures() -> list[dict[str, str]]:
    raw = FIXTURE_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != FIXTURE_SHA256:
        raise ValueError("SYNTHETIC_FIXTURE_CHANGED")
    data: list[dict[str, str]] = json.loads(raw)["examples"]
    return data


def synthetic_package(fixture_id: str) -> EvidencePackage:
    item = next((f for f in fixtures() if f["id"] == fixture_id), None)
    if item is None:
        raise ValueError("UNKNOWN_SYNTHETIC_FIXTURE")

    def uid(value: str) -> str:
        return str(uuid5(NAMESPACE_URL, "meridian-v5b/" + value))

    passages = (
        ()
        if not item["source"]
        else (
            Passage(
                uid(fixture_id + "/passage"),
                "observed_fact",
                item["source"],
                (uid(fixture_id + "/evidence"),),
                (uid(fixture_id + "/finding"),),
                "LOW",
            ),
        )
    )
    limits = (
        "Synthetic evaluation only; no real customer information.",
        "Human review required; no regulatory determination.",
        item["limitation"],
    )
    body = json.dumps([fixture_id, [vars(p) for p in passages], limits], sort_keys=True)
    return EvidencePackage(
        uid(fixture_id + "/case"),
        uid(fixture_id + "/run"),
        "COMPLETE" if passages else "INCOMPLETE_INSUFFICIENT_EVIDENCE",
        passages,
        limits,
        hashlib.sha256(body.encode()).hexdigest(),
    )


def identify_payload(payload: str) -> str:
    for item in fixtures():
        if payload == synthetic_package(item["id"]).payload():
            return item["id"]
    raise ValueError("SYNTHETIC_ONLY")
