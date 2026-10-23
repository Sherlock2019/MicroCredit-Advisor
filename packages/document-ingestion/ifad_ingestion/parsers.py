"""Parse uploaded bytes into page/section-addressable text.

PDF and DOCX parsing ported from CreditpappraisalFlowise backend/app/document_parser.py @ d3ff23f.
Markdown front matter (title, source_url, publication_date, license, ...) from SupplyChain_Predictions
backend/scinsight/rag.py @ 5c8dce6. Uploaded text is untrusted data; parsing never executes or interprets it.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

ALLOWED_TYPES = {".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv",
                 ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
MAX_PAGES = 300


class UnsupportedDocument(ValueError):
    pass


@dataclass
class ParsedSection:
    text: str
    page_number: int | None = None
    section: str | None = None


@dataclass
class ParsedDocument:
    sections: list[ParsedSection]
    metadata: dict[str, str] = field(default_factory=dict)


def extension(filename: str) -> str:
    match = re.search(r"\.[A-Za-z0-9]+$", filename or "")
    return match.group(0).lower() if match else ""


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        if key.strip():
            meta[key.strip().lower()] = value.strip()
    return meta, match.group(2)


def parse_markdown(data: bytes) -> ParsedDocument:
    meta, body = parse_front_matter(_decode(data))
    sections, current, lines = [], "Overview", []
    for line in body.splitlines():
        if line.startswith("## "):
            if "".join(lines).strip():
                sections.append(ParsedSection("\n".join(lines).strip(), None, current))
            current, lines = line[3:].strip(), []
        elif line.startswith("# "):
            meta.setdefault("title", line[2:].strip())
        else:
            lines.append(line)
    if "".join(lines).strip():
        sections.append(ParsedSection("\n".join(lines).strip(), None, current))
    return ParsedDocument(sections, meta)


def parse_pdf(data: bytes) -> ParsedDocument:
    import pymupdf

    sections: list[ParsedSection] = []
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise UnsupportedDocument("File is not a readable PDF") from exc
    with doc:
        if doc.page_count > MAX_PAGES:
            raise UnsupportedDocument(f"PDF has {doc.page_count} pages; the limit is {MAX_PAGES}")
        meta = {k: str(v) for k, v in (doc.metadata or {}).items() if v and k in {"title", "author", "subject"}}
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                sections.append(ParsedSection(text, index, None))
    return ParsedDocument(sections, meta)


def parse_docx(data: bytes) -> ParsedDocument:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with ZipFile(io.BytesIO(data)) as archive, archive.open("word/document.xml") as xml:
            root = ElementTree.parse(xml).getroot()  # noqa: S314 - stdlib parser does not resolve external entities
    except (BadZipFile, KeyError) as exc:
        raise UnsupportedDocument("File is not a readable DOCX") from exc
    paragraphs = ["".join(n.text or "" for n in p.findall(".//w:t", namespace)).strip() for p in root.findall(".//w:p", namespace)]
    text = "\n".join(p for p in paragraphs if p)
    return ParsedDocument([ParsedSection(text, None, None)] if text else [])


def parse_csv(data: bytes) -> ParsedDocument:
    rows = list(csv.reader(io.StringIO(_decode(data))))
    return ParsedDocument([ParsedSection("\n".join(" | ".join(r) for r in rows), None, "table")] if rows else [])


def parse_bytes(filename: str, data: bytes) -> ParsedDocument:
    ext = extension(filename)
    if ext not in ALLOWED_TYPES:
        raise UnsupportedDocument(f"Unsupported file type {ext or '(none)'}; allowed: {', '.join(sorted(ALLOWED_TYPES))}")
    if ext == ".pdf":
        if not data.startswith(b"%PDF"):
            raise UnsupportedDocument("File content is not a PDF")
        parsed = parse_pdf(data)
    elif ext == ".docx":
        parsed = parse_docx(data)
    elif ext == ".csv":
        parsed = parse_csv(data)
    elif ext == ".md":
        parsed = parse_markdown(data)
    else:
        parsed = ParsedDocument([ParsedSection(_decode(data), None, None)])
    if not any(s.text.strip() for s in parsed.sections):
        raise UnsupportedDocument("No extractable text (scanned documents need OCR, which this POC does not include)")
    return parsed
