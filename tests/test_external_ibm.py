import bz2
import csv
import io
from decimal import Decimal
from pathlib import Path

import pytest

from meridian.evaluation.external.ibm import HEADER, parse_row, transactions

pytestmark = pytest.mark.offline_guard_unit

# Hand-authored parser controls, NOT independent benchmark observations.
ROW = ["2019/01/01 00:12", "0001", "ABC", "0002", "DEF", "3.39",
       "US Dollar", "4.01", "Euro", "Wire", "1"]


def test_positional_accounts_and_exact_amounts() -> None:
    tx = parse_row(ROW, 2)
    assert (tx.sender_account, tx.receiver_account) == ("ABC", "DEF")
    assert tx.sender_bank == "0001"
    assert (tx.received, tx.paid) == (Decimal("3.39"), Decimal("4.01"))
    assert tx.timestamp.tzinfo is None
    assert tx.generator_label == 1


def test_publisher_null_amount_is_unknown_not_imputed() -> None:
    row = ROW.copy()
    row[5] = "(null)"
    row[6] = "Unknown"
    tx = parse_row(row, 2)
    assert tx.received is None
    assert tx.receiving_currency == "Unknown"
    assert tx.paid == Decimal("4.01")


@pytest.mark.parametrize("index,value", [
    (0, "2019/02/30 12:00"), (0, "2019/1/1 0:00"), (1, ""), (2, "A B"),
    (5, "NaN"), (5, "Infinity"), (5, "-1"), (7, "1e3"), (10, "2"),
    (6, ""), (8, " Euro"), (9, ""),
])
def test_invalid_fields(index: int, value: str) -> None:
    row = ROW.copy()
    row[index] = value
    with pytest.raises(ValueError, match="CSV row 42"):
        parse_row(row, 42)


@pytest.mark.parametrize("compressed", [False, True])
def test_stream_preserves_duplicates_and_row_identity(
    tmp_path: Path, compressed: bool,
) -> None:
    content = io.StringIO()
    csv.writer(content).writerows([HEADER, ROW, ROW])
    raw = content.getvalue().encode()
    path = tmp_path / ("input.csv.bz2" if compressed else "input.csv")
    path.write_bytes(bz2.compress(raw) if compressed else raw)
    result = list(transactions(path))
    assert [tx.row_number for tx in result] == [2, 3]


def test_wrong_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "input.csv"
    path.write_text("wrong,header\n")
    with pytest.raises(ValueError, match="header"):
        list(transactions(path))


def test_reader_preserves_signed_source_records(tmp_path: Path) -> None:
    row = ROW.copy()
    row[7] = "-4.01"
    path = tmp_path / "source.csv"
    with path.open("w", newline="") as stream:
        csv.writer(stream).writerows([HEADER, row])
    result = list(transactions(path))
    assert result[0].paid == Decimal("-4.01")
    assert result[0].generator_label == 1
