"""One fixed, synthetic customer. No generated-on-fetch or cross-account reads."""
from calendar import monthrange
from copy import deepcopy
from datetime import date, timedelta
from functools import lru_cache

AS_OF = date(2026, 10, 1)
DATASET_VERSION = "demo-2026-09-v1"


def add_months(day, count):
    index = day.year * 12 + day.month - 1 + count
    year, month = divmod(index, 12)
    return date(year, month + 1, min(day.day, monthrange(year, month + 1)[1]))


@lru_cache(maxsize=1)
def _transactions():
    rows = []
    categories = [("Food", "Cafe"), ("Shopping", "Store"), ("Travel", "Metro"),
                  ("Utilities", "Power"), ("Groceries", "Market"), ("Entertainment", "Cinema")]
    for month in range(4, 10):
        for index in range(40):
            category, merchant = categories[index % len(categories)]
            credit = index in (0, 20)
            if credit:
                category, merchant = ("Salary", "Demo Employer") if index == 0 else ("Transfer", "Savings transfer")
            rows.append({
                "id": f"TXN{2000 + len(rows)}", "date": date(2026, month, 1 + index * 28 // 40).isoformat(),
                "category": category, "merchant": merchant, "type": "credit" if credit else "debit",
                "amount": (70000 if index == 0 else 3000) if credit else 200 + ((index * 137 + month * 97) % 2100),
            })
    return sorted(rows, key=lambda row: (row["date"], row["id"]), reverse=True)


def transactions(page=None):
    rows = _transactions()
    if page is not None:
        rows = rows[max(0, page) * 20:(max(0, page) + 1) * 20]
    return deepcopy(rows)


@lru_cache(maxsize=5)
def _loan(loan_id):
    specs = {
        "LOAN001": ("Personal Loan", "Personal", 100000, 12.5, date(2023, 8, 15), 48, "HDFC Bank"),
        "LOAN002": ("Car Loan", "Auto", 500000, 9.5, date(2022, 2, 1), 72, "ICICI Bank"),
        "LOAN003": ("Home Loan", "Mortgage", 3000000, 8.0, date(2020, 1, 15), 240, "SBI"),
        "LOAN004": ("Education Loan", "Education", 200000, 10.5, date(2020, 7, 1), 48, "SBI"),
        "LOAN005": ("Business Loan", "Business", 750000, 14.0, date(2021, 1, 15), 36, "HDFC Bank"),
    }
    if loan_id not in specs:
        raise KeyError(loan_id)
    name, kind, amount, annual, start, months, lender = specs[loan_id]
    rate = annual / 1200
    emi = round(amount * rate / (1 - (1 + rate) ** -months), 2)
    balance, history = float(amount), []
    # Full recorded schedule through the fixed dataset date. Loan001 has real
    # unpaid installments; closed examples have paid off, never post-closure rows.
    for index in range(1, 301):
        due = add_months(start, index)
        if due >= AS_OF or balance <= 0:
            break
        status = "Missed" if loan_id == "LOAN001" and index in (8, 28) else "Late" if index % 11 == 0 else "Paid"
        interest = round(balance * rate, 2)
        payment = round(min(emi, balance + interest), 2) if status != "Missed" else 0
        principal = round(payment - interest, 2) if payment else 0
        if payment:
            balance = round(max(0, balance - principal), 2)
        history.append({
            "date": due.isoformat(), "month_year": due.strftime("%B %Y"), "due_date": due.isoformat(),
            "paid_date": (due + timedelta(days=3 if status == "Late" else 0)).isoformat() if payment else None,
            "amount": payment or None, "principal": principal or None, "interest": interest if payment else None,
            "status": status,
        })
    closed = balance == 0
    remaining, projected = 0, balance
    while projected > 0 and remaining < 600:
        projected = round(max(0, projected + round(projected * rate, 2) - emi), 2)
        remaining += 1
    result = {
        "id": loan_id, "name": name, "type": kind, "status": "Closed" if closed else "Active",
        "outstanding": balance, "original_amount": amount, "emi": 0 if closed else emi, "interest_rate": annual,
        "lender": lender, "account_number": "XXXX" + loan_id[-4:], "disbursement_date": start.isoformat(),
        "maturity_date": add_months(start, len(history) + remaining).isoformat(),
        "next_due_date": None if closed else add_months(start, len(history) + 1).isoformat(),
        "tenure_remaining": f"{remaining} months", "prepayment_charges": "Nil" if closed else "2% of outstanding",
        "late_payment_fee": 0 if closed else 500, "payment_history": list(reversed(history)),
        "total_paid": round(sum(row["amount"] or 0 for row in history), 2),
        "total_interest_paid": round(sum(row["interest"] or 0 for row in history), 2),
    }
    if closed:
        result["closed_date"] = history[-1]["paid_date"]
    if loan_id == "LOAN002":
        result["vehicle_details"] = {"make": "Honda", "model": "City", "year": 2022, "registration": "MH01AB1234"}
    if loan_id == "LOAN003":
        result["property_details"] = {"address": "123 Main Street, Mumbai", "property_value": 4000000, "type": "Apartment"}
    return result


def loan(loan_id, displayed=False):
    result = deepcopy(_loan(loan_id))
    if displayed:
        result["payment_history"] = result["payment_history"][:18]
    return result


def loan_summaries():
    fields = ("id", "name", "type", "status", "outstanding", "original_amount", "interest_rate", "emi", "next_due_date", "tenure_remaining", "closed_date")
    return [{key: value for key, value in loan(f"LOAN{i:03d}").items() if key in fields} for i in range(1, 6)]
