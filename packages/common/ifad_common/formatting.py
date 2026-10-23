"""Human-readable numbers for generated text. The grounding check ignores thousands separators and trailing zeros."""
from __future__ import annotations

from decimal import Decimal


def num(value) -> str:
    """6200.000 -> '6,200'; 3.300 -> '3.3'; None -> 'n/a'."""
    if value is None:
        return "n/a"
    d = Decimal(str(value))
    text = f"{d:,.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def money(value, currency: str) -> str:
    """2450000 -> '2,450,000.00 USD'."""
    if value is None:
        return "n/a"
    return f"{Decimal(str(value)):,.2f} {currency}"
