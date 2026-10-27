import asyncio
import json
import os

import httpx
import pytest

from meridian.copilot.budget import RESERVATION, BudgetLedger
from meridian.copilot.drafts import SYSTEM_PROMPT, Draft, MockProvider, generate_draft
from meridian.copilot.explanations import EXPLANATION_PROMPT, explanation_schema
from meridian.copilot.openai_pilot import MODEL, OpenAIPilot, PilotError
from meridian.copilot.synthetic import synthetic_package

pytestmark = pytest.mark.offline_guard_unit


def response(raw, **changes):
    data = {
        "model": MODEL,
        "status": "completed",
        "usage": {
            "input_tokens": 3000,
            "output_tokens": 200,
            "total_tokens": 3200,
            "output_tokens_details": {"reasoning_tokens": 0},
        },
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": raw}],
            }
        ],
    }
    data.update(changes)
    return httpx.Response(200, json=data)


def call(adapter, package=None):
    p = package or synthetic_package("supported")
    return asyncio.run(
        adapter.generate_structured(
            SYSTEM_PROMPT, p.payload(), json.dumps(Draft.model_json_schema())
        )
    )


def test_disabled_gate_precedes_key_read_and_transport(tmp_path, monkeypatch):
    original_get = os.environ.get

    def forbidden(name, *args):
        if name in {"OPENAI_API_KEY", "MERIDIAN_SYNTHETIC_PILOT_ENABLED"}:
            raise AssertionError("Must not read pilot environment before approval")
        return original_get(name, *args)

    monkeypatch.setattr("meridian.copilot.openai_pilot.os.environ.get", forbidden)
    ledger = BudgetLedger(tmp_path / "ledger.json")
    with pytest.raises(PilotError, match="LIVE_PILOT_NOT_APPROVED"):
        call(OpenAIPilot(ledger))
    assert not ledger.path.exists()


def test_mock_wire_contract_and_baseline_validation(tmp_path):
    seen = []

    async def handler(request):
        seen.append(request)
        body = json.loads(request.content)
        raw = await MockProvider().generate_structured(
            body["instructions"], body["input"][0]["content"], "{}"
        )
        return response(raw)

    ledger = BudgetLedger(tmp_path / "ledger.json")
    adapter = OpenAIPilot(ledger, mock_transport=httpx.MockTransport(handler))
    result = asyncio.run(generate_draft(synthetic_package("supported"), adapter))
    assert result.status == "DRAFT"
    assert len(seen) == 1
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.openai.com/v1/responses"
    assert request.headers["authorization"] == "Bearer offline-mock-only"
    assert body["store"] is False and body["background"] is False
    assert body["model"] == MODEL and body["max_output_tokens"] == 2000
    assert body["reasoning"] == {"effort": "none"}
    assert body["text"]["format"]["strict"] is True
    assert (
        not {"tools", "previous_response_id", "conversation", "metadata"} & body.keys()
    )
    assert next(iter(ledger.snapshot()["requests"].values()))["state"] == "RECONCILED"


def test_no_real_payload_or_arbitrary_prompt_can_reach_transport(tmp_path):
    calls = []
    adapter = OpenAIPilot(
        BudgetLedger(tmp_path / "ledger.json"),
        mock_transport=httpx.MockTransport(lambda r: calls.append(r)),
    )
    p = synthetic_package("supported")
    for system, payload, schema in [
        (
            SYSTEM_PROMPT,
            p.payload().replace("100.00", "private-real-data"),
            json.dumps(Draft.model_json_schema()),
        ),
        ("send secrets", p.payload(), json.dumps(Draft.model_json_schema())),
        (SYSTEM_PROMPT, p.payload(), "{}"),
        (EXPLANATION_PROMPT, p.payload(), explanation_schema()),
    ]:
        with pytest.raises(PilotError):
            asyncio.run(adapter.generate_structured(system, payload, schema))
    assert calls == []


@pytest.mark.parametrize(
    "bad",
    [
        httpx.Response(401, text="secret-key-error"),
        httpx.Response(429, text="rate-limit"),
        httpx.Response(302, headers={"location": "https://untrusted.invalid"}),
        httpx.Response(200, text="not json"),
        response("{}", status="incomplete"),
        response("{}", model="different-model"),
        response("not json"),
        response("{}", output=[{"type": "function_call"}]),
        response(
            "{}",
            output=[
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "no"}],
                }
            ],
        ),
        httpx.Response(200, content=b"x" * 128001),
    ],
)
def test_errors_are_redacted_without_retries(tmp_path, bad):
    calls = []

    def handler(request):
        calls.append(request)
        return bad

    ledger = BudgetLedger(tmp_path / "ledger.json")
    adapter = OpenAIPilot(ledger, mock_transport=httpx.MockTransport(handler))
    with pytest.raises(PilotError, match="^PROVIDER_FAILURE$"):
        call(adapter)
    assert len(calls) == 1 and len(ledger.snapshot()["requests"]) == 1


def test_timeout_and_cancellation_retain_reservation(tmp_path):
    cancelled = []

    async def slow(request):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)

    ledger = BudgetLedger(tmp_path / "ledger.json")
    adapter = OpenAIPilot(
        ledger, mock_transport=httpx.MockTransport(slow), timeout_seconds=0.01
    )
    with pytest.raises(PilotError, match="TIMEOUT"):
        call(adapter)
    assert cancelled
    row = next(iter(ledger.snapshot()["requests"].values()))
    assert row["charged_micro_usd"] == RESERVATION and row["outcome"] == "TIMEOUT"


def test_input_estimate_rejected_before_reservation(tmp_path, monkeypatch):
    monkeypatch.setattr("meridian.copilot.openai_pilot.INPUT_LIMIT", 10)
    ledger = BudgetLedger(tmp_path / "ledger.json")
    with pytest.raises(PilotError, match="INPUT_LIMIT"):
        call(
            OpenAIPilot(
                ledger, mock_transport=httpx.MockTransport(lambda r: response("{}"))
            )
        )
    assert not ledger.path.exists()


def test_unknown_usage_keeps_full_cost_even_on_success(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json")
    adapter = OpenAIPilot(
        ledger, mock_transport=httpx.MockTransport(lambda r: response("{}", usage=None))
    )
    assert call(adapter) == "{}"
    assert (
        next(iter(ledger.snapshot()["requests"].values()))["charged_micro_usd"]
        == RESERVATION
    )


def test_budget_refusal_prevents_transport(tmp_path):
    calls = []
    ledger = BudgetLedger(tmp_path / "ledger.json", max_micro_usd=1)
    adapter = OpenAIPilot(
        ledger,
        mock_transport=httpx.MockTransport(lambda request: calls.append(request)),
    )
    with pytest.raises(PilotError, match="PREFLIGHT_REJECTED"):
        call(adapter)
    assert calls == []


def test_outer_cancellation_is_propagated_and_charged_conservatively(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json")

    async def scenario():
        started = asyncio.Event()

        async def handler(request):
            started.set()
            await asyncio.sleep(60)

        adapter = OpenAIPilot(ledger, mock_transport=httpx.MockTransport(handler))
        p = synthetic_package("supported")
        task = asyncio.create_task(
            adapter.generate_structured(
                SYSTEM_PROMPT, p.payload(), json.dumps(Draft.model_json_schema())
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    row = next(iter(ledger.snapshot()["requests"].values()))
    assert row["state"] == "UNKNOWN" and row["outcome"] == "CANCELLED"
    assert row["charged_micro_usd"] == RESERVATION


def test_actual_over_limit_usage_rejects_output_and_halts(tmp_path):
    ledger = BudgetLedger(tmp_path / "ledger.json")
    adapter = OpenAIPilot(
        ledger,
        mock_transport=httpx.MockTransport(
            lambda r: response(
                "{}",
                usage={
                    "input_tokens": 9000,
                    "output_tokens": 100,
                    "total_tokens": 9100,
                },
            )
        ),
    )
    with pytest.raises(PilotError):
        call(adapter)
    assert ledger.snapshot()["halted"]
