import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from meridian.evaluation.external.references import fetch_sources

pytestmark = pytest.mark.offline_guard_unit


def spec(tmp_path: Path, filename: str = "source.pdf") -> Path:
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"sources": [{
        "filename": filename,
        "url": "https://www.bis.org/publications/example.pdf",
        "sha256": hashlib.sha256(b"%PDFexample").hexdigest(),
    }]}))
    return path


def test_verified_local_file_is_reused_without_network(tmp_path: Path) -> None:
    manifest = spec(tmp_path)
    directory = tmp_path / "cache"
    directory.mkdir()
    (directory / "source.pdf").write_bytes(b"%PDFexample")
    with patch("httpx.stream", side_effect=AssertionError("No network expected")):
        fetch_sources(manifest, directory)


def test_corrupt_local_file_is_not_overwritten(tmp_path: Path) -> None:
    manifest = spec(tmp_path)
    directory = tmp_path / "cache"
    directory.mkdir()
    path = directory / "source.pdf"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Existing reference digest"):
        fetch_sources(manifest, directory)
    assert path.read_bytes() == b"changed"


def test_reference_path_traversal_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="filename"):
        fetch_sources(spec(tmp_path, "../outside.pdf"), tmp_path / "cache")


def test_unreviewed_origin_rejected(tmp_path: Path) -> None:
    manifest = spec(tmp_path)
    source = json.loads(manifest.read_text())
    source["sources"][0]["url"] = "http://127.0.0.1/private"
    manifest.write_text(json.dumps(source))
    with pytest.raises(ValueError, match="origin"):
        fetch_sources(manifest, tmp_path / "cache")
