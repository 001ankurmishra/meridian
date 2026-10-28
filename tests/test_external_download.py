from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import httpx
import pytest

from meridian.evaluation.external.download_ibm import download

pytestmark = pytest.mark.offline_guard_unit


@contextmanager
def response(content: bytes, status: int = 200) -> Iterator[httpx.Response]:
    yield httpx.Response(status, content=content, request=httpx.Request("GET", "https://x"))


@pytest.mark.parametrize("body", [b"<html>error</html>", b"BZhshort", b"BZh" * 10])
def test_invalid_archive_never_published(tmp_path: Path, body: bytes) -> None:
    with patch("meridian.evaluation.external.download_ibm.EXPECTED_BYTES", 10), patch(
        "meridian.evaluation.external.download_ibm.httpx.stream",
        return_value=response(body),
    ):
        with pytest.raises(ValueError):
            download(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_receipt_and_no_overwrite(tmp_path: Path) -> None:
    body = b"BZhpayload"
    with patch(
        "meridian.evaluation.external.download_ibm.EXPECTED_BYTES", len(body),
    ), patch(
        "meridian.evaluation.external.download_ibm.httpx.stream",
        return_value=response(body),
    ):
        receipt = download(tmp_path)
    assert receipt["bytes"] == len(body)
    assert receipt["license"] == "CDLA-Sharing-1.0"
    assert "row validation pending" in str(receipt["validation_status"])
    with pytest.raises(FileExistsError):
        download(tmp_path)


def test_existing_partial_is_not_deleted(tmp_path: Path) -> None:
    partial = tmp_path / "trans_3000p2_list.txt.bz2.partial"
    partial.write_bytes(b"another process owns this")
    with pytest.raises(FileExistsError):
        download(tmp_path)
    assert partial.read_bytes() == b"another process owns this"


def test_http_error_removes_owned_partial(tmp_path: Path) -> None:
    with patch("meridian.evaluation.external.download_ibm.httpx.stream",
               return_value=response(b"", 404)):
        with pytest.raises(httpx.HTTPStatusError):
            download(tmp_path)
    assert list(tmp_path.iterdir()) == []
