import bz2
import csv
import io
from pathlib import Path

import pytest

from meridian.evaluation.external.ibm import HEADER, sha256_file
from meridian.evaluation.external.validate_ibm import anchor, validate

pytestmark = pytest.mark.offline_guard_unit


def archive(path: Path, rows: list[list[str]]) -> Path:
    text = io.StringIO()
    csv.writer(text).writerows([HEADER, *rows])
    path.write_bytes(bz2.compress(text.getvalue().encode()))
    return path


def test_validation_counts_conflicts_and_order(tmp_path: Path) -> None:
    row = ["2019/01/02 00:00", "1", "A", "2", "B", "1.00", "Euro",
           "1.00", "Euro", "Wire", "0"]
    conflict = [*row[:-1], "1"]
    earlier = row.copy()
    earlier[0] = "2019/01/01 00:00"
    invalid = row.copy()
    invalid[6] = ""
    path = archive(tmp_path / "data.bz2", [row, row, conflict, earlier, invalid])
    result = validate(path, tmp_path / "result", sha256_file(path))
    assert result["counts"]["rows"] == 5
    assert result["counts"]["valid_rows"] == 4
    assert result["counts"]["invalid_rows"] == 1
    assert result["counts"]["missing_fields"] == 1
    assert result["counts"]["out_of_order_transitions"] == 1
    assert result["duplicates"] == {
        "identical_record_excess": 1, "conflicting_label_groups": 1,
    }
    assert result["labels"] == {"0": 3, "1": 1}
    assert result["status"] == "INVALID_ROWS_PRESENT"


def test_hash_failure_precedes_output(tmp_path: Path) -> None:
    source = archive(tmp_path / "data.bz2", [])
    with pytest.raises(ValueError, match="SHA256"):
        validate(source, tmp_path / "result", "wrong")
    assert not (tmp_path / "result").exists()


def test_truncated_archive_never_claims_validation(tmp_path: Path) -> None:
    source = archive(tmp_path / "data.bz2", [])
    source.write_bytes(source.read_bytes()[:-8])
    with pytest.raises(EOFError):
        validate(source, tmp_path / "result", sha256_file(source))
    assert not (tmp_path / "result" / "validation.json").exists()


def test_anchor_sampling_is_stable_and_bank_scoped() -> None:
    results = [anchor("bank", str(i)) for i in range(10000)]
    assert 50 < sum(results) < 150
    assert results == [anchor("bank", str(i)) for i in range(10000)]
    assert results != [anchor("other", str(i)) for i in range(10000)]
