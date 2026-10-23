"""The vendored Banking Copilot loan-policy code must stay unchanged and agree with the Decimal engine."""
import hashlib
from decimal import Decimal as D
from pathlib import Path

import pytest
from ifad_credit_adapter import CreditPolicyAdapter
from ifad_credit_adapter.vendor import loan_policy
from rural_finance.services.cashflow import amortised_payment

VENDORED = Path(loan_policy.__file__)


def test_vendored_body_matches_recorded_upstream_hash():
    raw = VENDORED.read_bytes()
    lines = raw.splitlines(keepends=True)
    expected = next(ln for ln in lines if ln.startswith(b"#   sha256 of source:")).split(b":", 1)[1].strip().decode()
    upstream = b"".join(lines[5:])  # vendor.sh prepended exactly five provenance lines
    assert hashlib.sha256(upstream).hexdigest() == expected


@pytest.mark.parametrize("amount, rate, term", [("1500", "18", 10), ("12000", "14", 12), ("950", "0", 6), ("25000", "9.5", 36)])
def test_amortisation_agrees_with_banking_copilot_to_the_cent(amount, rate, term):
    ours = amortised_payment(D(amount), D(rate), term)
    theirs = CreditPolicyAdapter.amortised_monthly_payment(D(amount), D(rate), term)
    assert abs(ours - theirs) <= D("0.01")


def test_obligation_burden_uses_banking_bands_with_caveat():
    result = CreditPolicyAdapter.obligation_burden(D("300"), D("1000"))
    assert result["band"] == "Good" and result["ratio_pct"] == 30.0
    assert "seasonal" in result["caveat"]
    assert CreditPolicyAdapter.obligation_burden(D("100"), D("0"))["band"] == "Insufficient Evidence"


def test_banking_recommendation_never_allows_final_decision():
    assert loan_policy.determine_recommendation(10, 50, 0, [])["final_decision_allowed"] is False
