"""Window chunking with overlap and stable chunk references.

Window logic from CreditpappraisalFlowise document_parser.chunk_sections (sizes from SupplyChain scinsight/rag.py).
A chunk reference is "<document-uuid>#p<page>-c<index>": stable for a given document version, so citations remain
valid across re-indexing.
"""
from __future__ import annotations

from dataclasses import dataclass

from ifad_ingestion.parsers import ParsedSection

CHUNK_CHARS, OVERLAP = 900, 150


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    page_number: int | None
    section: str | None

    def reference(self, document_id: str) -> str:
        return f"{document_id}#p{self.page_number or 0}-c{self.index}"


def _windows(text: str, size: int, overlap: int) -> list[str]:
    out, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):  # prefer to cut at a sentence or word boundary
            cut = max(text.rfind(". ", start + size // 2, end), text.rfind(" ", start + size // 2, end))
            end = cut + 1 if cut > start else end
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        # Start the next window at a sentence boundary inside the overlap, so chunks do not begin mid-sentence.
        boundary = text.find(". ", end - overlap, end)
        start = boundary + 2 if boundary != -1 else max(start + 1, end - overlap)
    return [w for w in out if w]


def chunk_sections(sections: list[ParsedSection], size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in sections:
        text = " ".join(section.text.split())
        prefix = f"{section.section}: " if section.section and section.section != "table" else ""
        for window in _windows(text, size, overlap):
            chunks.append(Chunk(len(chunks), prefix + window, section.page_number, section.section))
    return chunks
