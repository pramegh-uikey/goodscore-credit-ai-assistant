import pytest
from fastapi.testclient import TestClient

import server
from agent import GroundedOutput, InvalidPageData, TransactionRow, loan_context, transaction_context


TRANSACTIONS = [
    {"id": "hidden-1", "date": "2026-09-01", "category": "Food", "merchant": "Cafe", "type": "debit", "amount": 100, "credit_score": 800},
    {"id": "hidden-2", "date": "2026-09-02", "category": "Food", "merchant": "Cafe", "type": "debit", "amount": 50},
    {"id": "hidden-3", "date": "2026-09-03", "category": "Salary", "merchant": "Employer", "type": "credit", "amount": 500},
]
LOAN = {
    "id": "LOAN001",
    "name": "Personal Loan",
    "status": "Active",
    "outstanding": 50000,
    "total_interest_paid": 18500,
    "next_due_date": "2026-09-30",
    "payment_history": [
        {"month_year": "September 2026", "due_date": "2026-09-01", "paid_date": None, "amount": 0, "principal": 0, "interest": 0, "status": "Pending", "secret": "hidden"}
    ],
    "credit_score": 800,
    "vehicle_details": {"make": "Honda", "model": "City", "year": 2022, "registration": "MH01AB1234"},
    "property_details": {"address": "Other loan property"},
}


def test_transaction_context_uses_displayed_rows_and_exact_totals():
    rows = [TransactionRow.model_validate(item) for item in TRANSACTIONS]
    context = transaction_context(rows)
    totals = context["calculated_from_displayed_rows"]
    assert totals["row_count"] == 3
    assert totals["debit_total_inr"] == 150
    assert totals["credit_total_inr"] == 500
    assert totals["net_credit_minus_debit_inr"] == 350
    assert totals["debit_by_category_inr"] == {"Food": 150}
    assert all("id" not in row and "credit_score" not in row for row in context["rows"])


def test_loan_context_excludes_hidden_and_other_status_fields():
    active = loan_context("LOAN001", LOAN)["displayed_loan"]
    assert active["next_due_date"] == "2026-09-30"
    assert "id" not in active
    assert "credit_score" not in active
    assert "vehicle_details" in active
    assert "property_details" not in active
    assert "secret" not in active["payment_history"][0]

    closed = loan_context("LOAN001", {**LOAN, "status": "Closed", "closed_date": "2026-09-01"})["displayed_loan"]
    assert closed["closed_date"] == "2026-09-01"
    assert closed["loan_duration"] == "Completed"
    assert "next_due_date" not in closed


@pytest.mark.parametrize("value", [0, -250, None])
def test_payment_placeholders_never_expose_underlying_numbers(value):
    loan = {**LOAN, "payment_history": [{
        **LOAN["payment_history"][0],
        "amount": value, "principal": value, "interest": value, "paid_date": "",
    }]}
    context = loan_context("LOAN001", loan)
    payment = context["displayed_loan"]["payment_history"][0]
    assert payment["amount"] is None
    assert payment["principal"] is None
    assert payment["interest"] is None
    assert payment["paid_date"] is None
    assert "unavailable, not zero" in context["note"]
    # Zero in a displayed overview field remains a real zero (e.g. a closed loan).
    assert loan_context("LOAN001", {**loan, "outstanding": 0})["displayed_loan"]["outstanding"] == 0


def test_positive_payment_values_are_preserved_exactly():
    payment = {"amount": 5000, "principal": 4500, "interest": 500, "paid_date": "2026-09-01"}
    loan = {**LOAN, "payment_history": [payment]}
    assert loan_context("LOAN001", loan)["displayed_loan"]["payment_history"] == [payment]


@pytest.mark.parametrize("value", ["500", True, float("inf"), float("nan")])
def test_invalid_payment_amounts_are_rejected(value):
    with pytest.raises(InvalidPageData, match="finite numbers"):
        loan_context("LOAN001", {**LOAN, "payment_history": [{"amount": value}]})


@pytest.mark.parametrize(
    ("route", "payload", "key"),
    [
        ("/transactions/ask", {"question": "How much did I spend?", "transactions": TRANSACTIONS}, "answer"),
        ("/transactions/summarize", {"transactions": TRANSACTIONS}, "summary"),
        ("/loans/ask", {"loan_id": "LOAN001", "question": "What interest have I paid?", "loan_data": LOAN}, "answer"),
        ("/loans/summarize", {"loan_id": "LOAN001", "loan_data": LOAN}, "summary"),
    ],
)
def test_four_routes_return_existing_contract(monkeypatch, route, payload, key):
    captured = {}

    def fake_model(context, action, question=None):
        captured.update(context=context, action=action, question=question)
        return GroundedOutput(supported=True, text="Grounded response.")

    monkeypatch.setattr(server, "generate_grounded_text", fake_model)
    response = TestClient(server.app).post(route, json=payload)
    assert response.status_code == 200
    assert response.json() == {key: "Grounded response."}
    assert captured["context"]["page"] in {"Transactions", "Loan Details"}
    assert "credit_score" not in str(captured["context"])


def test_unsupported_question_and_invalid_or_missing_page_data(monkeypatch):
    monkeypatch.setattr(
        server,
        "generate_grounded_text",
        lambda *args, **kwargs: GroundedOutput(supported=False, text=""),
    )
    client = TestClient(server.app)
    response = client.post(
        "/transactions/ask",
        json={"question": "What is my credit score?", "transactions": TRANSACTIONS},
    )
    assert response.status_code == 200
    assert response.json() == {"answer": "That information is not shown on this page."}
    assert client.post("/transactions/summarize", json={"transactions": []}).status_code == 400
    assert client.post(
        "/loans/ask",
        json={"loan_id": "OTHER", "question": "What is due?", "loan_data": LOAN},
    ).status_code == 400
    assert client.post(
        "/loans/ask",
        json={"loan_id": "LOAN001", "question": "  ", "loan_data": LOAN},
    ).status_code == 400


def test_model_failure_is_visible_without_fabricated_answer(monkeypatch):
    def failed_model(*args, **kwargs):
        raise RuntimeError("provider failure")

    monkeypatch.setattr(server, "generate_grounded_text", failed_model)
    response = TestClient(server.app).post(
        "/loans/summarize", json={"loan_id": "LOAN001", "loan_data": LOAN}
    )
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
