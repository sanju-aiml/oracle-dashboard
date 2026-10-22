"""Deterministic finance calculators: source of truth for training labels, eval, and runtime tool calls.
Tax slabs are CONFIG (they change every Budget) — update TAX_SLABS_NEW from the Finance Act before use."""
from __future__ import annotations

TAX_SLABS_NEW = [  # FY2025-26 new regime (verify against current Finance Act): (upper_limit, rate)
    (400000, 0.0), (800000, 0.05), (1200000, 0.10), (1600000, 0.15), (2000000, 0.20), (2400000, 0.25), (float("inf"), 0.30)]
STD_DEDUCTION_NEW = 75000
REBATE_87A_LIMIT, REBATE_87A_MAX = 1200000, 60000
CESS = 0.04

def gst(amount, rate_pct):
    g = amount * rate_pct / 100
    return {"gst": round(g, 2), "cgst": round(g / 2, 2), "sgst": round(g / 2, 2), "total": round(amount + g, 2)}

def emi(P, annual_pct, years):
    r, n = annual_pct / 1200, years * 12
    e = P * r * (1 + r) ** n / ((1 + r) ** n - 1)
    return {"emi": round(e, 2), "total_paid": round(e * n, 2), "total_interest": round(e * n - P, 2)}

def sip_fv(monthly, annual_pct, years):
    i, n = annual_pct / 1200, years * 12
    fv = monthly * ((1 + i) ** n - 1) / i
    return {"fv": fv, "invested": monthly * n, "gain": fv - monthly * n}

def compound(P, rate_pct, years, k=1):
    return round(P * (1 + rate_pct / 100 / k) ** (k * years), 2)

def tds_194c(amount, pan=True, payee="individual"):
    rate = (1.0 if payee in ("individual", "huf") else 2.0) if pan else 20.0
    applies = amount >= 30000
    tds = round(amount * rate / 100, 2) if applies else 0.0
    ex = (f"Section 194C: rate {rate}% ({'with' if pan else 'without'} PAN, payee {payee}). "
          f"{'Single-payment threshold ₹30,000 crossed' if applies else 'Below ₹30,000 single-payment threshold (annual ₹1,00,000 aggregate also applies)'}. "
          f"TDS = ₹{tds:,.2f}.")
    return {"tds": tds, "rate": rate, "explain": ex}

def hra_exemption(basic_monthly, hra_monthly, rent_monthly, metro=True):
    a = hra_monthly
    b = basic_monthly * (0.5 if metro else 0.4)
    c = max(0.0, rent_monthly - 0.1 * basic_monthly)
    ex = min(a, b, c)
    return {"exempt": round(ex, 2), "explain": (f"Least of: HRA received ₹{a:,.0f}; {'50%' if metro else '40%'} of basic ₹{b:,.0f}; "
                                               f"rent − 10% basic ₹{c:,.0f}. Exempt HRA = ₹{ex:,.2f}/month.")}

def tax_new_regime(gross_income):
    taxable = max(0.0, gross_income - STD_DEDUCTION_NEW)
    tax, prev = 0.0, 0.0
    for lim, rate in TAX_SLABS_NEW:
        if taxable > prev:
            tax += (min(taxable, lim) - prev) * rate
        prev = lim
    if taxable <= REBATE_87A_LIMIT:
        tax = max(0.0, tax - REBATE_87A_MAX)
    total = round(tax * (1 + CESS), 2)
    return {"taxable": taxable, "tax_before_cess": round(tax, 2), "total": total,
            "explain": f"Taxable = ₹{gross_income:,.0f} − ₹{STD_DEDUCTION_NEW:,} std deduction = ₹{taxable:,.0f}. Slab tax ₹{tax:,.2f} (after 87A rebate if eligible) + 4% cess = ₹{total:,.2f}."}
