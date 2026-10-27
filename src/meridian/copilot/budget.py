"""Single-host persistent pilot accounting; no database or remote service."""

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

INPUT_LIMIT = 8000
OUTPUT_LIMIT = 2000
# USD per million tokens = micro-USD per token; uncached standard rates.
RATE_VERSION = "openai-gpt-5.4-mini-2026-10-27:0.75:4.50"


def micro_cost(input_tokens: int, output_tokens: int) -> int:
    return (3 * input_tokens + 18 * output_tokens + 3) // 4


RESERVATION = micro_cost(INPUT_LIMIT, OUTPUT_LIMIT)


class BudgetError(ValueError):
    """Bounded error; no disk contents or credentials."""


class BudgetLedger:
    """One durable path per approved pilot, shared by all workers on one host.

    Local owner/filesystem are trusted. File loss/reset is not automatic recovery:
    reconcile with provider billing before a new pilot. Pending/unknown requests
    retain their entire reservation, including requests interrupted by a crash.
    """

    def __init__(
        self, path: Path, max_requests: int = 100, max_micro_usd: int = 5_000_000
    ) -> None:
        if (
            type(max_requests) is not int
            or not 1 <= max_requests <= 100
            or type(max_micro_usd) is not int
            or not 0 < max_micro_usd <= 5_000_000
        ):
            raise BudgetError("INVALID_LIMITS")
        self.max_requests = max_requests
        self.max_micro_usd = max_micro_usd
        self.path = path
        self.limits = {
            "max_requests": max_requests,
            "max_micro_usd": max_micro_usd,
            "rate_version": RATE_VERSION,
        }

    @contextmanager
    def _locked(self) -> Iterator[dict[str, Any]]:
        # Lock a stable separate inode; ledger is atomically replaced under it.
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with lock_path.open("a+") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self.path.exists():
                    data = json.loads(self.path.read_text())
                    if data["limits"] != self.limits:
                        raise BudgetError("LEDGER_CONFIGURATION_MISMATCH")
                else:
                    data = {"limits": self.limits, "halted": False, "requests": {}}
                yield data
            except BudgetError:
                raise
            except Exception:
                raise BudgetError("LEDGER_UNAVAILABLE") from None
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _save(self, data: dict[str, Any]) -> None:
        name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.path.parent, delete=False
            ) as stream:
                name = stream.name
                os.chmod(name, 0o600)
                json.dump(data, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
            with _directory(self.path.parent):
                pass
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def reserve(self, fixture_id: str, prompt_version: str) -> str:
        with self._locked() as data:
            records = data["requests"]
            used = sum(r["charged_micro_usd"] for r in records.values())
            if (
                data["halted"]
                or len(records) >= self.max_requests
                or used + RESERVATION > self.max_micro_usd
            ):
                raise BudgetError("PILOT_LIMIT_REACHED")
            request_id = str(uuid4())
            records[request_id] = {
                "state": "PENDING",
                "charged_micro_usd": RESERVATION,
                "fixture_id": fixture_id,
                "prompt_version": prompt_version,
                "usage": None,
            }
            self._save(data)
            return request_id

    def reconcile(
        self, request_id: str, usage: object, outcome: str, elapsed_seconds: float
    ) -> None:
        with self._locked() as data:
            row = data["requests"].get(request_id)
            if row is None or row["state"] != "PENDING":
                raise BudgetError("INVALID_RESERVATION")
            row.update(
                state="UNKNOWN", outcome=outcome, elapsed_seconds=elapsed_seconds
            )
            if isinstance(usage, dict):
                i, o = usage.get("input_tokens"), usage.get("output_tokens")
                if (
                    type(i) is int
                    and i > INPUT_LIMIT
                    or type(o) is int
                    and o > OUTPUT_LIMIT
                ):
                    data["halted"] = True
                total = usage.get("total_tokens")
                details = usage.get("output_tokens_details")
                reasoning = (
                    details.get("reasoning_tokens")
                    if isinstance(details, dict)
                    else None
                )
                if (
                    type(i) is int
                    and type(o) is int
                    and min(i, o) >= 0
                    and type(total) is int
                    and total == i + o
                    and (
                        reasoning is None
                        or (type(reasoning) is int and 0 <= reasoning <= o)
                    )
                ):
                    row.update(
                        state="RECONCILED",
                        charged_micro_usd=micro_cost(i, o),
                        usage={
                            "input_tokens": i,
                            "output_tokens": o,
                            "reasoning_tokens": reasoning,
                            "total_tokens": total,
                        },
                    )
                    # output_tokens already includes reasoning; never add it twice.
                    if i > INPUT_LIMIT or o > OUTPUT_LIMIT:
                        data["halted"] = True
            if (
                sum(r["charged_micro_usd"] for r in data["requests"].values())
                > self.max_micro_usd
            ):
                data["halted"] = True
            self._save(data)

    def snapshot(self) -> dict[str, Any]:
        with self._locked() as data:
            return data


@contextmanager
def _directory(path: Path) -> Iterator[None]:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
        yield
    finally:
        os.close(fd)
