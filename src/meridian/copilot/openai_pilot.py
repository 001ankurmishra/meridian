"""Disabled OpenAI Responses REST adapter, using the already locked httpx client.

No SDK dependency, runtime registration, tool support or configurable endpoint.
Only checked-in synthetic payloads and the two fixed prompt/schema pairs qualify.
"""

import asyncio
import json
import os
import time
from typing import Any, Final

import httpx

from meridian.copilot.budget import INPUT_LIMIT, OUTPUT_LIMIT, BudgetError, BudgetLedger
from meridian.copilot.drafts import PROMPT_VERSION, SYSTEM_PROMPT, Draft
from meridian.copilot.explanations import (
    EXPLANATION_PROMPT,
    EXPLANATION_VERSION,
    explanation_schema,
)
from meridian.copilot.synthetic import identify_payload

MODEL: Final = "gpt-5.4-mini-2026-03-17"
# Must be changed only by a reviewed commit after explicit maintainer approval.
APPROVED_PILOT_ID: str | None = None
ENDPOINT: Final = "https://api.openai.com/v1/responses"


class PilotError(ValueError):
    """Bounded provider error; no remote payload, header, key or traceback detail."""


class OpenAIPilot:
    model_identifier = MODEL

    def __init__(
        self,
        ledger: BudgetLedger,
        *,
        mock_transport: httpx.MockTransport | None = None,
        experimental: bool = False,
        timeout_seconds: float = 10,
    ) -> None:
        if not 0 < timeout_seconds <= 10:
            raise PilotError("INVALID_TIMEOUT")
        if (
            mock_transport is not None
            and type(mock_transport) is not httpx.MockTransport
        ):
            raise PilotError("MOCK_TRANSPORT_REQUIRED")
        self.ledger = ledger
        self.mock_transport = mock_transport
        self.experimental = experimental
        self.timeout_seconds = timeout_seconds

    async def generate_structured(
        self, system: str, package_json: str, schema_json: str
    ) -> str:
        # Gate before reading any credential, parsing payload or reserving budget.
        if self.mock_transport is None and (
            APPROVED_PILOT_ID is None
            or os.environ.get("MERIDIAN_SYNTHETIC_PILOT_ENABLED") != APPROVED_PILOT_ID
        ):
            raise PilotError("LIVE_PILOT_NOT_APPROVED")
        if self.mock_transport is None and self.ledger.pilot_id != APPROVED_PILOT_ID:
            raise PilotError("PILOT_ACCOUNTING_ID_MISMATCH")
        if self.mock_transport is None:
            try:
                self.ledger.snapshot()
            except BudgetError:
                raise PilotError("ACCOUNTING_STATE_INVALID") from None
        try:
            fixture_id = identify_payload(package_json)
            if (
                system == SYSTEM_PROMPT
                and json.loads(schema_json) == Draft.model_json_schema()
            ):
                version = PROMPT_VERSION
            elif (
                self.experimental
                and system == EXPLANATION_PROMPT
                and json.loads(schema_json) == json.loads(explanation_schema())
            ):
                version = EXPLANATION_VERSION
            else:
                raise PilotError("PROMPT_SCHEMA_NOT_APPROVED")
            payload: dict[str, Any] = {
                "model": MODEL,
                "store": False,
                "background": False,
                "instructions": system,
                "input": [{"role": "user", "content": package_json}],
                "max_output_tokens": OUTPUT_LIMIT,
                "reasoning": {"effort": "none"},
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "meridian_draft",
                        "strict": True,
                        "schema": json.loads(schema_json),
                    }
                },
            }
            # Conservative UTF-8 byte bound plus fixed envelope allowance. This
            # is not provider-tokenizer certification; reconcile actual usage.
            wire = json.dumps(
                payload, separators=(",", ":"), ensure_ascii=True
            ).encode()
            if len(wire) + 1024 > INPUT_LIMIT:
                raise PilotError("INPUT_LIMIT")
            key = (
                "offline-mock-only"
                if self.mock_transport
                else os.environ.get("OPENAI_API_KEY")
            )
            if not key:
                raise PilotError("CREDENTIAL_UNAVAILABLE")
            reservation = self.ledger.reserve(fixture_id, version)
        except PilotError:
            raise
        except Exception:
            raise PilotError("PREFLIGHT_REJECTED") from None
        start = time.monotonic()
        usage: object = None
        outcome = "UNKNOWN"
        try:
            async with asyncio.timeout(self.timeout_seconds):
                transport = self.mock_transport or httpx.AsyncHTTPTransport(retries=0)
                async with httpx.AsyncClient(
                    transport=transport,
                    timeout=httpx.Timeout(self.timeout_seconds),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    async with client.stream(
                        "POST",
                        ENDPOINT,
                        content=wire,
                        headers={
                            "Authorization": "Bearer " + key,
                            "Content-Type": "application/json",
                        },
                    ) as response:
                        if response.status_code != 200:
                            raise PilotError("PROVIDER_ERROR")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 128000:
                                raise PilotError("RESPONSE_TOO_LARGE")
                        result = json.loads(body)
            usage = result.get("usage")
            if result.get("model") != MODEL or result.get("status") != "completed":
                raise PilotError("INCOMPLETE_OR_MODEL_MISMATCH")
            if isinstance(usage, dict) and (
                type(usage.get("input_tokens")) is int
                and usage["input_tokens"] > INPUT_LIMIT
                or type(usage.get("output_tokens")) is int
                and usage["output_tokens"] > OUTPUT_LIMIT
            ):
                raise PilotError("ACTUAL_TOKEN_LIMIT")
            texts = []
            for item in result["output"]:
                if item.get("type") == "reasoning":
                    continue
                if item.get("type") != "message" or item.get("role") != "assistant":
                    raise PilotError("UNEXPECTED_OUTPUT")
                for content in item["content"]:
                    if (
                        content.get("type") != "output_text"
                        or type(content.get("text")) is not str
                    ):
                        raise PilotError("REFUSAL_OR_INVALID_OUTPUT")
                    texts.append(content["text"])
            if len(texts) != 1 or len(texts[0].encode()) > 64000:
                raise PilotError("INVALID_OUTPUT")
            # Schema and grounding are still checked by the separate validators.
            json.loads(texts[0])
            outcome = "RECEIVED"
            return str(texts[0])
        except asyncio.CancelledError:
            outcome = "CANCELLED"
            raise
        except (TimeoutError, httpx.TimeoutException):
            outcome = "TIMEOUT"
            raise PilotError("TIMEOUT") from None
        except Exception:
            outcome = "PROVIDER_FAILURE"
            raise PilotError("PROVIDER_FAILURE") from None
        finally:
            # Sync durable update also runs on cancellation. No refund for absent
            # or malformed usage: the request may have been charged remotely.
            self.ledger.reconcile(reservation, usage, outcome, time.monotonic() - start)
