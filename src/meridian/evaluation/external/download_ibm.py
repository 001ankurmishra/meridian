"""Download the publisher's original archive into ignored scratch storage.

Run with the locked development environment. No Kaggle credentials are needed.
An interrupted transfer never becomes the final artifact; no archive extraction.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

URL = (
    "https://ibm.box.com/index.php?rm=box_download_shared_file"
    "&shared_name=vqecdqbyuyobc8s0fd8zkf3dp0ba0ed5&file_id=f_780504045395"
)
EXPECTED_BYTES = 839740068


def download(directory: Path) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "trans_3000p2_list.txt.bz2"
    partial = target.with_suffix(".bz2.partial")
    if target.exists():
        raise FileExistsError("Archive exists; validate it rather than overwrite")
    digest = hashlib.sha256()
    size = 0
    output = partial.open("xb")
    try:
        with output:
            with httpx.stream(
                "GET", URL, follow_redirects=True, timeout=60,
            ) as response:
                response.raise_for_status()
                for block in response.iter_bytes(1024 * 1024):
                    size += len(block)
                    if size > EXPECTED_BYTES:
                        raise ValueError("Publisher artifact exceeds documented size")
                    if size == len(block) and not block.startswith(b"BZh"):
                        raise ValueError("Publisher did not return a bzip2 archive")
                    output.write(block)
                    digest.update(block)
            output.flush()
            os.fsync(output.fileno())
        if size != EXPECTED_BYTES:
            raise ValueError("Publisher artifact size differs from documentation")
        # Exclusive publication prevents concurrent invocations replacing an artifact.
        os.link(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    receipt: dict[str, object] = {
        "dataset": "IBM AML Dataset A, February 2021",
        "source_url": URL,
        "publisher_url": "https://github.com/IBM/AML-Data",
        "license": "CDLA-Sharing-1.0",
        "license_url": "https://cdla.dev/sharing-1-0/",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "bytes": size,
        "sha256": digest.hexdigest(),
        "checksum_status": "LOCALLY_OBSERVED; no publisher SHA256 supplied",
        "validation_status": "DOWNLOADED; row validation pending",
        "filename": target.name,
    }
    directory.joinpath("download-receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8",
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    print(json.dumps(download(args.directory), indent=2))
