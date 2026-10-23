"""Grounding checks applied to every model-generated text before it is shown or stored.

- citations: every [n] must point at supplied evidence, and at least one citation must be present;
- numbers: every number in generated text must appear in the deterministic facts or the cited evidence
  (the "LLM never invents numbers" rule from SupplyChain_Predictions SCInsight, applied here);
- support: the share of cited sentences whose content words overlap their cited evidence.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from ifad_models.embeddings import tokenize

_NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?%?")
_CITE = re.compile(r"\[(\d+)\]")


def check_citations(text: str, evidence_count: int) -> dict:
    cited = [int(n) for n in _CITE.findall(text or "")]
    invalid = sorted({n for n in cited if not 1 <= n <= evidence_count})
    return {"valid": bool(cited) and not invalid, "cited": sorted(set(cited)), "invalid": invalid}


def _normalise(token: str) -> str | None:
    raw = token.rstrip("%").replace(",", "")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    return format(value.normalize(), "f")


def numbers_in(text: str) -> set[str]:
    out = set()
    for match in _NUM.findall(text or ""):
        norm = _normalise(match)
        if norm is not None:
            out.add(norm)
    return out


def check_numbers(generated: str, allowed_sources: list[str]) -> dict:
    """Numbers in `generated` that appear in none of the sources. Citation markers and years are ignored."""
    allowed: set[str] = set()
    for source in allowed_sources:
        allowed |= numbers_in(source)
    body = _CITE.sub("", generated or "")
    found = numbers_in(body)
    unsupported = sorted(n for n in found if n not in allowed and not re.fullmatch(r"(19|20)\d\d", n))
    return {"valid": not unsupported, "unsupported_numbers": unsupported, "numbers_checked": len(found)}


def evidence_support(answer: str, evidence_texts: list[str], threshold: float = 0.5) -> dict:
    """Share of cited sentences whose content words are mostly present in the evidence they cite."""
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", answer or "") if s.strip()]
    checked = supported = 0
    for sentence in sentences:
        refs = [int(n) for n in _CITE.findall(sentence) if 1 <= int(n) <= len(evidence_texts)]
        words = set(tokenize(_CITE.sub("", sentence)))
        if not refs or not words:
            continue
        checked += 1
        evidence_words = set().union(*(set(tokenize(evidence_texts[r - 1])) for r in refs))
        if len(words & evidence_words) / len(words) >= threshold:
            supported += 1
    return {"sentences_checked": checked, "sentences_supported": supported,
            "supported_ratio": round(supported / checked, 3) if checked else 0.0}
