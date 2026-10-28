"""Checksum-pinned PDF reference intake for isolated, noncommercial evaluation.

No application database writes. Outputs contain copyright text and must remain
in ignored scratch storage. Every chunk retains source, page and status metadata.
"""

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pypdf

from meridian.evaluation.external.ibm import sha256_file


def fetch_sources(manifest: Path, directory: Path) -> None:
    """Fetch only pinned official PDFs; reuse verified local files."""
    import httpx

    directory.mkdir(parents=True, exist_ok=True)
    for source in json.loads(manifest.read_text())["sources"]:
        if Path(source["filename"]).name != source["filename"]:
            raise ValueError("Invalid reference filename")
        if not source["url"].startswith("https://www.bis.org/publications/"):
            raise ValueError("Unreviewed reference download origin")
        path = directory / source["filename"]
        if path.exists():
            if sha256_file(path) != source["sha256"]:
                raise ValueError("Existing reference digest mismatch")
            continue
        content = bytearray()
        with httpx.stream("GET", source["url"], timeout=30) as response:
            response.raise_for_status()
            for block in response.iter_bytes(65536):
                content.extend(block)
                if len(content) > 10_000_000:
                    raise ValueError("Reference exceeds reviewed size limit")
        if not content.startswith(b"%PDF"):
            raise ValueError("Reference response is not a PDF")
        if hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError("Downloaded reference digest mismatch")
        with path.open("xb") as output:
            output.write(content)


def chunks(text: str, token_count: Callable[[str], int]) -> list[str]:
    """Use original text spans, <=400 BGE tokens, overlapping at most 30 words."""
    words = list(re.finditer(r"\S+", text))
    result = []
    start = 0
    while start < len(words):
        end = min(start + 180, len(words))
        while end > start:
            span = text[words[start].start() : words[end - 1].end()]
            if token_count(span) <= 400:
                break
            end -= 1
        if end == start:
            raise ValueError("Unchunkable reference token")
        result.append(span)
        if end == len(words):
            break
        overlap = min(30, (end - start) // 5)
        start = end - overlap
    return result


def ingest(manifest: Path, directory: Path, output: Path) -> dict[str, Any]:
    from meridian.agents.policy.chunking import tokenizer

    spec = json.loads(manifest.read_text())
    records = []
    pages = 0
    for source in spec["sources"]:
        path = directory / source["filename"]
        if sha256_file(path) != source["sha256"]:
            raise ValueError("Reference PDF digest mismatch")
        pdf = pypdf.PdfReader(path, strict=True)
        if len(pdf.pages) != source["pages"]:
            raise ValueError("Reference PDF page count mismatch")
        for number, page in enumerate(pdf.pages, start=1):
            if number <= 2:
                continue
            text = re.sub(r"\s+", " ", page.extract_text()).strip()
            if number in source.get("verified_blank_pdf_pages", []):
                if text:
                    raise ValueError("Previously blank page now has content")
                continue
            if not text:
                raise ValueError("Empty reference page requires manual review")
            pages += 1
            for index, chunk in enumerate(
                chunks(text, lambda s: len(tokenizer.encode(s, verbose=False)))
            ):
                records.append(
                    {
                        "chunk_id": f"{source['id']}:pdf-page-{number}:chunk-{index}",
                        "source_id": source["id"],
                        "title": source["title"],
                        "version": source["version"],
                        "pdf_page": number,
                        "section": f"PDF page {number}; section not inferred",
                        "source_url": source["url"],
                        "status": source["status"],
                        "jurisdiction": source["jurisdiction"],
                        "document_type": source["document_type"],
                        "effective_date": source["effective_date"],
                        "is_synthetic": False,
                        "is_bank_policy": False,
                        "text": chunk,
                        "sha256": hashlib.sha256(chunk.encode()).hexdigest(),
                        "copyright": source["copyright"],
                    }
                )
    payload = "".join(json.dumps(row, sort_keys=True) + "\n" for row in records)
    with output.open("x") as stream:
        stream.write(payload)
    return {
        "documents": len(spec["sources"]),
        "pages": pages,
        "chunks": len(records),
        "manifest_sha256": sha256_file(manifest),
        "chunks_sha256": sha256_file(output),
        "pypdf_version": pypdf.__version__,
        "chunking": "Page-confined spans; <=400 BGE tokens; <=30 word overlap",
        "use_scope": spec["use_scope"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        fetch_sources(args.manifest, args.directory)
    print(json.dumps(ingest(args.manifest, args.directory, args.output), indent=2))
