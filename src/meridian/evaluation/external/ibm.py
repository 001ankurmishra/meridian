"""Strict, streaming reader for IBM's original February 2021 AML CSV.

The two identically named Account columns are positional, not DictReader keys.
Labels describe IBM's generator, never a regulatory determination.
"""

import bz2
import csv
import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

HEADER = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account",
    "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency",
    "Payment Format", "Is Laundering",
]


@dataclass(frozen=True)
class Transaction:
    row_number: int
    timestamp: datetime  # Source timezone is unspecified; do not invent UTC.
    sender_bank: str
    sender_account: str
    receiver_bank: str
    receiver_account: str
    received: Decimal
    receiving_currency: str
    paid: Decimal
    payment_currency: str
    payment_format: str
    generator_label: int


def parse_row(row: list[str], row_number: int) -> Transaction:
    """Reject malformed records with bounded errors, without printing row data."""
    try:
        if len(row) != len(HEADER):
            raise ValueError("column count")
        if any(not value or value != value.strip() for value in row):
            raise ValueError("empty or padded field")
        if not re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", row[0]):
            raise ValueError("timestamp format")
        timestamp = datetime.strptime(row[0], "%Y/%m/%d %H:%M")
        if any(not re.fullmatch(r"[A-Za-z0-9]+", v) for v in row[1:5]):
            raise ValueError("identifier format")
        amounts = []
        for index in (5, 7):
            if not re.fullmatch(r"\d+(?:\.\d+)?", row[index]):
                raise ValueError("amount format")
            amount = Decimal(row[index])
            if not amount.is_finite() or amount < 0:
                raise ValueError("amount range")
            amounts.append(amount)
        if row[10] not in {"0", "1"}:
            raise ValueError("label")
        return Transaction(
            row_number, timestamp, row[1], row[2], row[3], row[4], amounts[0], row[6],
            amounts[1], row[8], row[9], int(row[10]),
        )
    except (ValueError, InvalidOperation) as exc:
        raise ValueError(f"Invalid IBM transaction at CSV row {row_number}") from exc


def transactions(path: Path) -> Iterator[Transaction]:
    """Read bounded-memory records, retaining duplicate rows and source positions."""
    opener = bz2.open if path.suffix == ".bz2" else open
    with opener(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != HEADER:
            raise ValueError("Unexpected IBM CSV header")
        for number, row in enumerate(reader, start=2):
            yield parse_row(row, number)


def sha256_file(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
