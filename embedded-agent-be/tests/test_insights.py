from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import demo_history as repository
import insights
import server
from agent import GroundedOutput, TransactionRow, loan_context, transaction_context
from financial_math import calculate_scenario, emi
from insights_types import Exchange, InsightOutput, RouteDecision, Scenario


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ENABLE_INSIGHTS", "true")
    return TestClient(server.app)


def decision(route="insights", scope="history", **kwargs):
    return RouteDecision(route=route, scope=scope, resolved_question="How can I improve?", **kwargs)


def txn_context():
    return transaction_context([TransactionRow.model_validate(row) for row in repository.transactions(0)])


def test_dataset_is_finite_stable_and_isolated_from_mutation(client):
    pages = [client.get(f"/transactions?page={page}").json() for page in range(13)]
    assert all(len(page) == 20 for page in pages[:-1]) and pages[-1] == []
    all_rows = [row for page in pages for row in page]
    assert all_rows == repository.transactions()
    assert len({row["id"] for row in all_rows}) == 240
    assert all_rows == sorted(all_rows, key=lambda r: (r["date"], r["id"]), reverse=True)
    pages[0][0]["amount"] = -1
    assert client.get("/transactions?page=0").json()[0]["amount"] >= 0
    assert client.get("/transactions?page=-1").status_code == 400
    assert client.get("/transactions/top").json() == sorted(all_rows, key=lambda row: row["amount"], reverse=True)[:5]


@pytest.mark.parametrize("loan_id", [f"LOAN{i:03d}" for i in range(1, 6)])
def test_loan_history_and_overview_reconcile(client, loan_id):
    full = repository.loan(loan_id)
    visible = client.get("/loans/details/" + loan_id).json()
    assert len(visible["payment_history"]) == 18
    assert visible["payment_history"] == full["payment_history"][:18]
    assert len(full["payment_history"]) > 18
    paid_principal = sum(row["principal"] or 0 for row in full["payment_history"])
    assert full["outstanding"] == pytest.approx(full["original_amount"] - paid_principal, abs=.02)
    assert full["total_paid"] == pytest.approx(sum(row["amount"] or 0 for row in full["payment_history"]))
    for row in full["payment_history"]:
        assert row["due_date"] >= full["disbursement_date"]
        if row["amount"] is not None:
            assert row["amount"] == pytest.approx(row["principal"] + row["interest"])
        if full["status"] == "Closed":
            assert row["due_date"] <= full["closed_date"]
    summary = next(row for row in client.get("/loans/summary").json() if row["id"] == loan_id)
    assert all(full[key] == value for key, value in summary.items())


def test_history_context_covers_all_rows_and_explicit_dates():
    context, coverage = insights.build_context(txn_context(), None, decision())
    assert coverage["record_count"] == 240 and coverage["complete_available_history"]
    assert "calculated_from_displayed_rows" not in context
    assert context["calculated_from_history"]["credit_total_inr"] == 438000
    assert sum(row["debit_inr"] for row in context["monthly_totals"].values()) == context["calculated_from_history"]["debit_total_inr"]
    _, narrow = insights.build_context(txn_context(), None, decision(start_date="2026-08-01", end_date="2026-08-31"))
    assert narrow["record_count"] == 40 and not narrow["complete_available_history"]
    _, empty = insights.build_context(txn_context(), None, decision(start_date="2030-01-01"))
    assert empty["record_count"] == 0 and empty["from"] is None


def test_displayed_scope_does_not_read_history(monkeypatch):
    def forbidden(*args):
        raise AssertionError("No history retrieval allowed")
    context = txn_context()
    monkeypatch.setattr(repository, "transactions", forbidden)
    built, coverage = insights.build_context(context, None, decision(scope="displayed"))
    assert coverage["record_count"] == 20
    assert len(built["rows"]) == 20


def test_selected_loan_is_the_only_account_read(monkeypatch):
    context = loan_context("LOAN002", repository.loan("LOAN002", displayed=True))
    original = repository.loan
    calls = []
    def only_selected(loan_id):
        calls.append(loan_id)
        assert loan_id == "LOAN002"
        return original(loan_id)
    monkeypatch.setattr(repository, "loan", only_selected)
    built, coverage = insights.build_context(context, "LOAN002", decision())
    assert calls == ["LOAN002"] and coverage["record_count"] > 18
    assert built["displayed_loan"]["name"] == "Car Loan"
    assert sum(built["payment_status_counts"].values()) == coverage["record_count"]
    assert "Personal Loan" not in str(built) and "Home Loan" not in str(built)


def test_direct_route_and_summary_preserve_old_context(client, monkeypatch):
    calls = []
    monkeypatch.setattr(insights, "classify", lambda *args: decision("direct", "displayed"))
    def old(context, action, question=None):
        calls.append((context, action, question))
        return GroundedOutput(supported=True, text="Old answer")
    monkeypatch.setattr(server, "generate_grounded_text", old)
    rows = repository.transactions(0)
    response = client.post("/transactions/ask", json={"transactions": rows, "question": "Total?"})
    assert response.json()["mode"] == "direct" and len(calls[0][0]["rows"]) == 20
    monkeypatch.setattr(insights, "classify", lambda *args: pytest.fail("Summary must bypass router"))
    response = client.post("/transactions/summarize", json={"transactions": rows})
    assert response.json() == {"summary": "Old answer"} and calls[-1][1] == "summarize"


def test_feature_off_bypasses_new_calls(client, monkeypatch):
    monkeypatch.setenv("ENABLE_INSIGHTS", "false")
    monkeypatch.setattr(insights, "classify", lambda *args: pytest.fail("Flag off"))
    monkeypatch.setattr(server, "generate_grounded_text", lambda *args: GroundedOutput(supported=False, text=""))
    response = client.post("/transactions/ask", json={"transactions": repository.transactions(0), "question": "Advice?"})
    assert response.json() == {"answer": "That information is not shown on this page."}
    assert client.get("/assistant/config").json() == {"insights_enabled": False}


def test_insights_retrieves_backend_records_and_returns_coverage(client, monkeypatch):
    monkeypatch.setattr(insights, "classify", lambda *args: decision())
    def model(stage, prompt, payload, schema):
        assert payload["context"]["coverage"]["record_count"] == 240
        assert all(row["amount"] != 999999999 for row in payload["context"]["rows"])
        return InsightOutput(observations=["Six months of recorded transactions."], suggestions=["Review recurring spending."])
    monkeypatch.setattr(insights, "model_json", model)
    rows = repository.transactions(0)
    rows[0]["amount"] = 999999999
    response = client.post("/transactions/ask", json={"transactions": rows, "question": "Help me improve"})
    assert response.status_code == 200
    assert response.json()["coverage"]["record_count"] == 240


@pytest.mark.parametrize("stage", ["router", "insights"])
def test_model_failure_returns_error_not_old_refusal(client, monkeypatch, stage):
    monkeypatch.setattr(server, "generate_grounded_text", lambda *args: pytest.fail("No fallback"))
    def model(current, *args):
        if current == stage:
            raise TimeoutError()
        return decision()
    monkeypatch.setattr(insights, "model_json", model)
    response = client.post("/transactions/ask", json={"transactions": repository.transactions(0), "question": "Advice?"})
    assert response.status_code == 503 and "temporarily unavailable" in response.json()["detail"]


def test_invalid_requests_never_reach_router(client, monkeypatch):
    monkeypatch.setattr(insights, "classify", lambda *args: pytest.fail("Invalid request"))
    assert client.post("/loans/ask", json={"loan_id": "LOAN002", "loan_data": repository.loan("LOAN001"), "question": "Advice?"}).status_code == 400
    payload = {"transactions": repository.transactions(0), "question": "Advice?"}
    assert client.post("/transactions/ask", json={**payload, "history": [{"question": "a", "answer": "b"}] * 11}).status_code == 422
    assert client.post("/transactions/ask", json={**payload, "history": [{"question": "a", "answer": "b" * 10000}] * 4}).status_code == 422
    assert client.post("/transactions/ask", json={**payload, "question": " "}).status_code == 400


def number(value, quote):
    return {"value": value, "quote": quote}


def emi_scenario(**overrides):
    return Scenario.model_validate({"kind": "emi", "principal": number(500000, "5 lakh"),
        "annual_rate_min": number(8, "8%"), "annual_rate_max": number(12, "12%"), "months": number(60, "5 years"), **overrides})


def test_independent_amortization_examples_and_zero_rate():
    result = calculate_scenario(emi_scenario(), "5 lakh at 8% to 12% for 5 years")
    assert result["range_inr"] == [10138.20, 11122.22]
    assert emi(120000, 0, 12) == 10000
    assert emi(100000, 12, 1) == pytest.approx(101000)
    scenario = Scenario.model_validate({"kind": "principal", "annual_rate_min": number(0, "0%"), "annual_rate_max": number(0, "0%"),
        "months": number(12, "12 months"), "budget_min": number(10000, "10k"), "budget_max": number(20000, "20k")})
    assert calculate_scenario(scenario, "0%, 12 months, budget 10k to 20k")["range_inr"] == [120000, 240000]


def test_missing_fabricated_and_invalid_scenario_inputs():
    assert "principal" in calculate_scenario(emi_scenario(), "8% to 12% for 5 years")["missing_inputs"]
    assert "principal" in calculate_scenario(emi_scenario(principal=number(700000, "5 lakh")), "5 lakh 8% 12% 5 years")["missing_inputs"]
    assert "invalid_inputs" in calculate_scenario(emi_scenario(months=number(0, "0 months")), "5 lakh 8% 12% 0 months")
    assert "invalid_inputs" in calculate_scenario(emi_scenario(annual_rate_min=number(15, "15%")), "5 lakh 15% 12% 5 years")
    with pytest.raises(ValidationError):
        emi_scenario(principal=number(float("inf"), "infinite"))


def test_followup_uses_user_inputs_and_server_renders_estimate(monkeypatch):
    monkeypatch.setattr(insights, "model_json", lambda *args: InsightOutput(suggestions=["Review this payment against your budget."]))
    history = [Exchange(question="A 5 lakh loan for 5 years", answer="Which annual rate range?")]
    response = insights.answer_insights(txn_context(), None, "8% to 12%", history, decision(scenario=emi_scenario()))
    assert "10,138.20–11,122.22" in response["answer"]
    assert "not an approval" in response["answer"]
    assert "range_inr" not in calculate_scenario(emi_scenario(), "A loan for 5 years, 8% to 12%")


def test_missing_assumptions_get_server_followup_without_invented_examples(monkeypatch):
    monkeypatch.setattr(insights, "model_json", lambda *args: InsightOutput(
        observations=["Recorded payments are available."], follow_up="Try my invented rates of 9%–11%?"))
    result = insights.answer_insights(txn_context(), None, "5 lakh for 5 years", [], decision(scenario=emi_scenario()))
    assert "annual interest rate" in result["answer"]
    assert "9%" not in result["answer"] and "Illustrative monthly EMI:" not in result["answer"]


def test_structured_model_call_configuration_and_malformed_output(monkeypatch):
    captured = {}
    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(parsed={"route": "direct", "scope": "displayed", "resolved_question": "What is my balance?"}, usage_metadata=None)
    monkeypatch.setattr(insights, "_gemini_client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    assert insights.classify("Balance?", "Loan Details", []).route == "direct"
    assert captured["config"].http_options.timeout == 15000
    assert captured["config"].http_options.retry_options.attempts == 1
    assert "page_context" not in captured["contents"]
    assert captured["config"].automatic_function_calling.disable
    with pytest.raises(ValidationError):
        RouteDecision(route="direct", scope="history", resolved_question="Invalid")
    with pytest.raises(ValidationError):
        RouteDecision(route="insights", scope="history", resolved_question="Invalid", start_date="2026-09-30", end_date="2026-09-01")


@pytest.mark.parametrize("response", [
    SimpleNamespace(parsed=None, text="{broken", usage_metadata=None),
    SimpleNamespace(parsed={"route": "anywhere", "scope": "history"}, usage_metadata=None),
    SimpleNamespace(parsed={"route": "direct", "scope": "displayed", "resolved_question": "Valid but truncated"},
                    candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")], usage_metadata=None),
])
def test_invalid_or_truncated_generation_is_rejected(monkeypatch, response):
    monkeypatch.setattr(insights, "_gemini_client", lambda: SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: response)))
    with pytest.raises(ValueError):
        insights.classify("Question", "Transactions", [])


def test_no_supported_output_or_unknown_loan_is_not_fabricated(client, monkeypatch):
    monkeypatch.setattr(insights, "classify", lambda *args: decision())
    monkeypatch.setattr(insights, "model_json", lambda *args: InsightOutput())
    response = client.post("/transactions/ask", json={"transactions": repository.transactions(0), "question": "Advice?"})
    assert response.status_code == 503
    loan = {**repository.loan("LOAN002", displayed=True), "id": "UNKNOWN"}
    response = client.post("/loans/ask", json={"loan_id": "UNKNOWN", "loan_data": loan, "question": "Advice?"})
    assert response.status_code == 400


def test_displayed_loan_context_does_not_recover_missing_values(monkeypatch):
    loan = repository.loan("LOAN001", displayed=True)
    loan["payment_history"][0]["amount"] = None
    source = loan_context("LOAN001", loan)
    monkeypatch.setattr(repository, "loan", lambda *args: pytest.fail("Displayed analysis must not fetch history"))
    result, coverage = insights.build_context(source, "LOAN001", decision(scope="displayed"))
    assert result["displayed_loan"]["payment_history"][0]["amount"] is None
    assert coverage["scope"] == "displayed" and coverage["record_count"] == 18
