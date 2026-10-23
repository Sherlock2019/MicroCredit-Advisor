"""Instruction-like text detector for untrusted document content.

Pattern ported from SupplyChain_Predictions backend/scinsight/rag.py::INJECTION @ 5c8dce6, extended for the
finance and project domains. Flagged chunks are stored (they are evidence that someone tried) but are excluded
from model context, and document text is only ever placed in the user turn as quoted data.
"""
from __future__ import annotations

import re

INJECTION = re.compile(
    r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)|disregard (the |all )?(system|previous|prior)"
    r"|you are now|new instructions:|system prompt|reveal (your )?(system )?(prompt|instructions|key|secret)"
    r"|approve (this|the|my) (loan|application|report)|mark (this|the) (loan|application|report) (as )?approved"
    r"|set (the )?(status|state|decision) to|override (the )?(policy|system|rules)|act as (an? )?(admin|reviewer)"
    r"|grant (me|yourself) (access|the role)|call the (review|approval) (tool|endpoint)",
    re.IGNORECASE,
)


def injection_flags(text: str) -> list[str]:
    return ["contains_instruction_like_text"] if INJECTION.search(text or "") else []
