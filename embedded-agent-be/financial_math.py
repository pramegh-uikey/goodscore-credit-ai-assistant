"""Deterministic scenario estimates from explicitly supplied numbers."""
import math
import re
from decimal import Decimal, ROUND_HALF_UP

from insights_types import Scenario


def money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def emi(principal, annual_rate, months):
    rate = annual_rate / 1200
    return principal / months if rate == 0 else principal * rate / -math.expm1(-months * math.log1p(rate))


def _explicit_value(item, user_text, field):
    """Require a quoted user source and its number, including common INR units."""
    if item is None:
        return None
    quote = item.quote.casefold()
    if quote not in user_text.casefold():
        return None
    candidates = []
    for match in re.finditer(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?\s*(crores?|lakhs?|lacs?|thousand|k\b|years?|yrs?|months?)?", quote):
        number = float(re.match(r"-?[\d,.]+", match.group(0))[0].replace(",", ""))
        unit = (match.group(1) or "").strip()
        factor = 10000000 if unit.startswith("crore") else 100000 if unit.startswith(("lakh", "lac")) else 1000 if unit in ("k", "thousand") else 12 if field == "months" and unit.startswith(("year", "yr")) else 1
        candidates.append(number * factor)
    return item.value if any(math.isclose(item.value, value, rel_tol=1e-9) for value in candidates) else None


def calculate_scenario(scenario: Scenario, user_text: str):
    if scenario.kind == "none":
        return {"kind": "none"}
    required = ["annual_rate_min", "annual_rate_max", "months"] + (["principal"] if scenario.kind == "emi" else ["budget_min", "budget_max"])
    values = {name: _explicit_value(getattr(scenario, name), user_text, name) for name in required}
    missing = [name for name, value in values.items() if value is None]
    if missing:
        return {"kind": scenario.kind, "missing_inputs": missing, "instruction": "Ask for explicit rate bounds, tenure and principal or monthly repayment-budget bounds as needed. Never invent values."}
    low, high, months = values["annual_rate_min"], values["annual_rate_max"], values["months"]
    if not (0 <= low <= high <= 100 and 1 <= months <= 600 and months.is_integer()):
        return {"kind": scenario.kind, "invalid_inputs": "Use ordered annual rates from 0 to 100 percent and a whole-number tenure of 1–600 months."}
    if scenario.kind == "emi":
        principal = values["principal"]
        if principal <= 0:
            return {"kind": "emi", "invalid_inputs": "Principal must be positive."}
        bounds = emi(principal, low, months), emi(principal, high, months)
    else:
        bottom, top = values["budget_min"], values["budget_max"]
        if not (0 < bottom <= top):
            return {"kind": "principal", "invalid_inputs": "Monthly repayment budgets must be positive and ordered."}
        bounds = bottom / emi(1, high, months), top / emi(1, low, months)
    return {"kind": scenario.kind, "range_inr": [money(value) for value in bounds], "inputs": values,
            "assumptions": "Fixed interest, equal monthly payments, no fees or insurance; user-supplied assumptions, not a lender offer."}


def render_scenario(result):
    if "range_inr" not in result:
        return ""
    low, high = result["range_inr"]
    values = result["inputs"]
    label = "Illustrative monthly EMI" if result["kind"] == "emi" else "Illustrative affordable principal"
    source = f"principal INR {values['principal']:,.2f}" if result["kind"] == "emi" else f"monthly repayment budget INR {values['budget_min']:,.2f}–{values['budget_max']:,.2f}"
    return (f"{label}: INR {low:,.2f}–{high:,.2f}.\n"
            f"Inputs: {source}; annual interest {values['annual_rate_min']:g}–{values['annual_rate_max']:g}%; {values['months']:g} months.\n"
            f"{result['assumptions']} This is not an approval or eligibility prediction.")


def scenario_follow_up(result):
    """Ask for required assumptions without the model proposing made-up rates."""
    if "invalid_inputs" in result:
        return "Please correct the scenario inputs: " + result["invalid_inputs"]
    missing = set(result.get("missing_inputs", []))
    labels = []
    if "principal" in missing:
        labels.append("the proposed loan amount")
    if missing.intersection(("annual_rate_min", "annual_rate_max")):
        labels.append("the annual interest rate or minimum/maximum rates you want to assume")
    if "months" in missing:
        labels.append("the repayment tenure in months or years")
    if missing.intersection(("budget_min", "budget_max")):
        labels.append("your monthly repayment budget or budget range after existing commitments")
    return "To calculate an illustrative range, please provide " + "; ".join(labels) + "." if labels else ""
