"""Opt-in provider checks against synthetic records; no credentials in output."""
import os

import pytest
from fastapi.testclient import TestClient

import demo_history
import insights
import server
from insights_types import Exchange

pytestmark = pytest.mark.skipif(os.getenv("RUN_LIVE_INSIGHTS") != "1", reason="Opt-in: real Gemini calls")


@pytest.mark.parametrize("question,page,route,scope", [
    ("What is my total debit across the displayed rows?", "Transactions", "direct", "displayed"),
    ("What is my credit score?", "Transactions", "direct", "displayed"),
    ("Write a poem about Mars", "Transactions", "direct", "displayed"),
    ("How could I improve my spending habits based on my history?", "Transactions", "insights", "history"),
    ("What is my total spending across all available history, including older rows?", "Transactions", "insights", "history"),
    ("Suggest ways to save using only the 20 displayed transactions", "Transactions", "insights", "displayed"),
    ("What is my EMI and how could I reduce the pressure on my budget?", "Loan Details", "insights", "history"),
    ("Based on this loan's history, how can I improve my credit score?", "Loan Details", "insights", "history"),
    ("What is the EMI on my other home loan?", "Loan Details", "direct", "displayed"),
    ("What exact interest amount is hidden behind '-' in the displayed payment row?", "Loan Details", "direct", "displayed"),
])
def test_live_router(question, page, route, scope):
    result = insights.classify(question, page, [])
    assert (result.route, result.scope) == (route, scope)


def test_live_correction_extracts_latest_user_inputs():
    history = [Exchange(question="Estimate EMI for 5 lakh at 8% to 12% for 5 years", answer="Illustrative estimate based on your inputs.")]
    result = insights.classify("Actually use 6 lakh, keep the rates and tenure the same", "Loan Details", history)
    assert result.route == "insights"
    assert result.scenario.principal.value == 600000
    assert result.scenario.months.value == 60


def test_live_api_personalized_advice_and_numeric_range(monkeypatch):
    monkeypatch.setenv("ENABLE_INSIGHTS", "true")
    client = TestClient(server.app)
    response = client.post("/transactions/ask", json={
        "transactions": demo_history.transactions(0),
        "question": "Using all my transaction history, suggest specific ways I could improve my spending. Quote relevant categories or months from the data.",
    })
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["mode"] == "insights" and body["coverage"]["record_count"] == 240
    assert "Suggestions:" in body["answer"]
    assert any(category in body["answer"].lower() for category in ("food", "travel", "shopping", "groceries", "entertainment", "utilities"))
    response = client.post("/loans/ask", json={
        "loan_id": "LOAN002", "loan_data": demo_history.loan("LOAN002", displayed=True),
        "question": "What principal range could a monthly repayment budget of INR 10,000 to INR 20,000 support, over 12 months, at 0% annual interest? Explain this as a scenario, not eligibility.",
    })
    assert response.status_code == 200, response.json()
    assert "120,000.00–240,000.00" in response.json()["answer"]
