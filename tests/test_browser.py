"""Browser acceptance checks against the README's running frontend/backend.

Default tests use deterministic GET fixtures and stub assistant responses.
RUN_LIVE_GEMINI=1 also exercises the real four chat endpoints and Gemini.
"""

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import expect, sync_playwright


FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:3000")
API = "http://localhost:8000"  # Matches the supplied frontend config.js.
REFUSAL = "That information is not shown on this page."


def transaction_batch(batch):
    if batch > 1:
        return []
    return [
        {
            "id": f"hidden-{batch}-{index}",
            "date": "2026-09-01",
            "category": "Food" if index < 15 else "Salary",
            "merchant": "Cafe" if index < 15 else "Employer",
            "type": "debit" if index < 15 else "credit",
            "amount": (100 if index < 15 else 200) + batch * 200,
            "credit_score": 899,
        }
        for index in range(20)
    ]


def loan_fixture(loan_id):
    closed = loan_id == "LOAN004"
    return {
        "id": loan_id,
        "name": "Car Loan" if closed else "Personal Loan",
        "type": "Vehicle" if closed else "Personal",
        "status": "Closed" if closed else "Active",
        "outstanding": 0 if closed else 50000,
        "original_amount": 800000 if closed else 200000,
        "emi": 0 if closed else 5000,
        "total_paid": 875000 if closed else 150000,
        "total_interest_paid": 75000 if closed else 18500,
        "interest_rate": 9.5 if closed else 12,
        "lender": "Fixture Bank",
        "account_number": "****1234",
        "disbursement_date": "2022-01-01",
        "maturity_date": "2027-01-01",
        "next_due_date": "2026-09-30",
        "tenure_remaining": "10 months",
        "closed_date": "2025-12-01",
        "prepayment_charges": "2%",
        "late_payment_fee": 500,
        "credit_score": 899,
        "vehicle_details": {"make": "Honda", "model": "City", "year": 2022, "registration": "MH01AB1234"},
        "property_details": {"address": "Hidden property", "type": "Apartment", "property_value": 9000000},
        "payment_history": [
            {"month_year": "September 2026", "due_date": "2026-09-01", "paid_date": "2026-09-01", "amount": 5000, "principal": 5250, "interest": -250, "status": "Paid", "secret": "hidden"},
            {"month_year": "August 2026", "due_date": "2026-08-01", "paid_date": None, "amount": 0, "principal": 0, "interest": 0, "status": "Pending"},
            {"month_year": "July 2026", "due_date": "2026-07-01", "paid_date": "2026-07-01", "amount": 6000, "principal": 5000, "interest": 1000, "status": "Paid"},
        ],
    }


@pytest.fixture
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("BROWSER_CHANNEL"))
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        local_client = None
        if os.getenv("E2E_IN_PROCESS") == "1":
            from browser_harness import attach
            local_client = attach(page, FRONTEND, API)

        def transactions(route):
            batch = int(parse_qs(urlparse(route.request.url).query)["page"][0])
            route.fulfill(json=transaction_batch(batch))

        def loans(route):
            loan_id = route.request.url.rsplit("/", 1)[1]
            route.fulfill(json=loan_fixture(loan_id))

        page.route(API + "/transactions?*", transactions)
        page.route(API + "/loans/details/*", loans)
        yield page
        context.close()
        browser.close()
        if local_client:
            local_client.close()
        assert not errors, f"Uncaught browser errors: {errors}"


def assistant_route(page, prefix, replies):
    """Capture real browser payloads; return an explicit sequence of test outcomes."""
    payloads = []

    def respond(route):
        payloads.append(route.request.post_data_json)
        status, message = replies.pop(0)
        key = "detail" if status != 200 else ("answer" if route.request.url.endswith("/ask") else "summary")
        route.fulfill(status=status, json={key: message})

    page.route(API + prefix + "/ask", respond)
    page.route(API + prefix + "/summarize", respond)
    return payloads


def screenshot(page, name):
    directory = os.getenv("BROWSER_ARTIFACTS")
    if directory:
        destination = Path(directory)
        destination.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(destination / f"{name}.png"), full_page=True)


def test_navigation_reaches_real_pages_and_widgets(page):
    page.goto(FRONTEND)
    expect(page.locator("h1")).to_have_text("Financial Dashboard")
    page.get_by_role("link", name="View 6 months").click()
    expect(page).to_have_title("Transactions")
    expect(page.locator("#txn-summary-button")).to_be_enabled()

    page.goto(FRONTEND)
    page.get_by_role("link", name="View all loans").click()
    expect(page).to_have_title("Loan History")
    page.locator('a[href="loan-details.html#id=LOAN001"]').click()
    expect(page).to_have_title("Loan Details")
    expect(page.locator("#loan-title")).to_have_text("Personal Loan - Detailed View")
    expect(page.locator("#loan-ask-button")).to_be_enabled()
    page.get_by_role("link", name="Back to Dashboard").click()
    page.locator('a[href="loan-details.html#id=LOAN001"]').click()
    expect(page.locator("#loan-summary-button")).to_be_enabled()

    for path, title, button in [
        ("/transactions", "Transactions", "#txn-ask-button"),
        ("/loans", "Loan History", None),
        ("/loan-details?id=LOAN004", "Loan Details", "#loan-ask-button"),
        ("/loan-details#id=LOAN001", "Loan Details", "#loan-summary-button"),
    ]:
        page.goto(FRONTEND + path)
        expect(page).to_have_title(title)
        if button:
            expect(page.locator(button)).to_be_enabled()
    screenshot(page, "loan-widget")

    # Also render the supplied backend's actual demo responses (no GET fixtures).
    page.unroute(API + "/transactions?*")
    page.unroute(API + "/loans/details/*")
    page.goto(FRONTEND + "/transactions")
    expect(page.locator("#table tr")).to_have_count(21)
    expect(page.locator("#txn-summary-button")).to_be_enabled()
    page.locator("#txn-load-more").click()
    expect(page.locator("#table tr")).to_have_count(41)
    for loan_id in ("LOAN001", "LOAN003", "LOAN004"):
        page.goto(FRONTEND + "/loan-details?id=" + loan_id)
        expect(page.locator("#payment-history tr")).to_have_count(19)
        expect(page.locator("#loan-summary-button")).to_be_enabled()
        if loan_id == "LOAN003":
            expect(page.locator("#additional-details")).to_contain_text("Property Details")


def test_transactions_payload_pagination_and_error_recovery(page):
    replies = [(200, "Summary of 20 rows."), (503, "The assistant is temporarily unavailable."), (200, "<b>Recovered answer</b>"), (200, REFUSAL)]
    payloads = assistant_route(page, "/transactions", replies)
    page.goto(FRONTEND + "/transactions")
    expect(page.locator("#table tr")).to_have_count(21)
    page.locator("#txn-ask-button").click()
    expect(page.locator("#txn-ai-response-text")).to_contain_text("Enter a question")
    assert payloads == []
    page.locator("#txn-summary-button").click()
    expect(page.locator("#txn-ai-response-text")).to_have_text("Summary of 20 rows.")
    assert len(payloads[0]["transactions"]) == 20
    assert set(payloads[0]["transactions"][0]) == {"date", "category", "merchant", "type", "amount"}

    page.locator("#txn-load-more").click()
    expect(page.locator("#table tr")).to_have_count(41)
    expect(page.locator("#txn-ai-response")).to_be_hidden()
    page.locator("#txn-question").fill("What is my total spend?")
    page.locator("#txn-ask-button").click()
    expect(page.locator("#txn-ai-response-text")).to_contain_text("temporarily unavailable")
    expect(page.locator("#txn-summary-button")).to_be_enabled()
    expect(page.locator("#txn-load-more")).to_be_enabled()
    page.locator("#txn-ask-button").click()
    expect(page.locator("#txn-ai-response-text")).to_have_text("<b>Recovered answer</b>")
    expect(page.locator("#txn-ai-response-text b")).to_have_count(0)
    assert len(payloads[2]["transactions"]) == 40
    assert sum(row["amount"] for row in payloads[2]["transactions"] if row["type"] == "debit") == 6000

    page.locator("#txn-question").fill("What is my credit score?")
    page.locator("#txn-ask-button").click()
    expect(page.locator("#txn-ai-response-text")).to_have_text(REFUSAL)
    page.locator("#txn-load-more").click()
    expect(page.locator("#txn-load-status")).to_have_text("No more transactions.")
    expect(page.locator("#txn-load-more")).to_be_disabled()
    expect(page.locator("#txn-ask-button")).to_be_enabled()
    assert not replies
    screenshot(page, "transactions-widget")


@pytest.mark.parametrize("loan_id", ["LOAN001", "LOAN004"])
def test_loan_visible_values_match_payload_and_errors_recover(page, loan_id):
    replies = [(200, "Loan summary."), (503, "The assistant is temporarily unavailable."), (200, "<b>Recovered answer</b>"), (200, REFUSAL)]
    payloads = assistant_route(page, "/loans", replies)
    page.goto(FRONTEND + "/loan-details?id=" + loan_id)
    expect(page.locator("#payment-history tr")).to_have_count(4)
    expect(page.locator("#payment-history tr").nth(1).locator("td").nth(5)).to_have_text("-")
    for column in (2, 3, 4, 5):
        expect(page.locator("#payment-history tr").nth(2).locator("td").nth(column)).to_have_text("-")
    page.locator("#loan-ask-button").click()
    expect(page.locator("#ai-response-text")).to_contain_text("Enter a question")
    assert payloads == []
    page.locator("#loan-summary-button").click()
    expect(page.locator("#ai-response-text")).to_have_text("Loan summary.")
    data = payloads[0]["loan_data"]
    assert payloads[0]["loan_id"] == data["id"] == loan_id
    assert "credit_score" not in data and "property_details" not in data
    assert data["payment_history"][0]["interest"] is None
    assert data["payment_history"][0]["amount"] == 5000
    assert "secret" not in data["payment_history"][0]
    assert all(data["payment_history"][1][field] is None for field in ("amount", "principal", "interest", "paid_date"))
    if loan_id == "LOAN004":
        assert "next_due_date" not in data and "tenure_remaining" not in data
        assert data["loan_duration"] == "Completed" and data["outstanding"] == 0
        expect(page.locator("#loan-info")).not_to_contain_text("Next Due Date")
    else:
        assert "closed_date" not in data and "loan_duration" not in data
        expect(page.locator("#loan-info")).not_to_contain_text("Closed Date")

    page.locator("#user-question").fill("How much interest have I paid?")
    page.locator("#loan-ask-button").click()
    expect(page.locator("#ai-response-text")).to_contain_text("temporarily unavailable")
    expect(page.locator("#loan-summary-button")).to_be_enabled()
    page.locator("#loan-ask-button").click()
    expect(page.locator("#ai-response-text")).to_have_text("<b>Recovered answer</b>")
    expect(page.locator("#ai-response-text b")).to_have_count(0)
    page.locator("#user-question").fill("What is my credit score?")
    page.locator("#loan-ask-button").click()
    expect(page.locator("#ai-response-text")).to_have_text(REFUSAL)
    assert not replies


def live_answer(page, kind, question=None):
    prefix = "txn" if kind == "transactions" else "loan"
    output = "#txn-ai-response-text" if prefix == "txn" else "#ai-response-text"
    action = "ask" if question is not None else "summarize"
    if question is not None:
        page.locator("#txn-question" if prefix == "txn" else "#user-question").fill(question)
    button = f"#{prefix}-{'ask' if action == 'ask' else 'summary'}-button"
    with page.expect_response(API + f"/{kind}/{action}", timeout=120000) as response:
        page.locator(button).click()
        expect(page.locator(button)).to_be_disabled()
        if prefix == "txn":
            expect(page.locator("#txn-load-more")).to_be_disabled()
    assert response.value.status == 200, response.value.text()
    expect(page.locator(button)).to_be_enabled(timeout=120000)
    answer = page.locator(output).inner_text()
    assert answer and answer not in ("Thinking...", "Generating summary...")
    print(json.dumps({"page": kind, "question": question, "answer": answer}, ensure_ascii=False), flush=True)
    return answer


def digits(answer):
    return re.sub(r"[,\s]", "", answer)


@pytest.mark.skipif(os.getenv("RUN_LIVE_GEMINI") != "1", reason="Opt-in: requires configured Gemini and spends model quota")
def test_live_gemini_through_browser_with_known_financial_fixtures(page):
    page.goto(FRONTEND + "/transactions")
    expect(page.locator("#txn-summary-button")).to_be_enabled()
    summary = live_answer(page, "transactions")
    assert "20" in summary and "1500" in digits(summary) and "1000" in digits(summary)
    answer = live_answer(page, "transactions", "What is the total debit amount across the currently displayed rows?")
    assert "1500" in digits(answer)
    assert live_answer(page, "transactions", "What is my credit score?") == REFUSAL
    page.locator("#txn-load-more").click()
    expect(page.locator("#table tr")).to_have_count(41)
    answer = live_answer(page, "transactions", "What is the total debit amount across the currently displayed rows?")
    assert "6000" in digits(answer)
    screenshot(page, "live-transactions")

    for loan_id, interest in [("LOAN001", "18500"), ("LOAN004", "75000")]:
        page.goto(FRONTEND + "/loan-details?id=" + loan_id)
        expect(page.locator("#loan-summary-button")).to_be_enabled()
        summary = live_answer(page, "loans")
        assert loan_fixture(loan_id)["name"].lower() in summary.lower()
        assert "-250" not in digits(summary)
        answer = live_answer(page, "loans", "What is my total interest paid for this loan?")
        assert interest in digits(answer)
        assert live_answer(page, "loans", "What is my total spending on the Transactions page?") == REFUSAL
        assert live_answer(page, "loans", "What exact interest amount is shown in the September 2026 payment row?") == REFUSAL
        screenshot(page, "live-" + loan_id)
