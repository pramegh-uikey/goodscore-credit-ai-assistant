import os

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_harness import attach
import insights
import server
from agent import GroundedOutput
from insights_types import InsightOutput, RouteDecision

FRONTEND = "http://insights.test"
API = "http://api.insights.test"


@pytest.fixture
def page(monkeypatch, request):
    monkeypatch.setenv("ENABLE_INSIGHTS", "true")
    if not request.node.name.startswith("test_live_"):
        def model(stage, prompt, payload, schema):
            if stage == "router":
                question = payload["question"]
                if question == "fail":
                    raise TimeoutError()
                route = "direct" if question == "What is my total spend?" else "insights"
                return RouteDecision(route=route, scope="displayed" if route == "direct" else "history", resolved_question=question)
            context = payload["context"]
            count = context["coverage"]["record_count"]
            return InsightOutput(observations=[f"Read {count} records. <b>Literal text</b>"],
                                 follow_up="What monthly repayment budget would you like to use?")
        monkeypatch.setattr(insights, "model_json", model)
        monkeypatch.setattr(server, "generate_grounded_text", lambda *args: GroundedOutput(supported=True, text="Original flow answer."))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.getenv("BROWSER_CHANNEL", "chrome"))
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        client = attach(page, FRONTEND, API)
        yield page
        client.close()
        context.close()
        browser.close()
        assert not errors


def ask(page, question, kind="txn"):
    field = "#txn-question" if kind == "txn" else "#user-question"
    button = f"#{kind}-ask-button"
    path = "/transactions/ask" if kind == "txn" else "/loans/ask"
    page.locator(field).fill(question)
    with page.expect_response(API + path, timeout=120000) as response:
        page.locator(button).click()
    expect(page.locator(button)).to_be_enabled()
    return response.value


def test_history_followup_reset_and_safe_rendering(page):
    payloads = []
    page.on("request", lambda req: payloads.append(req.post_data_json) if req.url == API + "/transactions/ask" else None)
    page.goto(FRONTEND + "/transactions")
    expect(page.locator("#txn-new-conversation")).to_be_visible()
    expect(page.locator("#table tr")).to_have_count(21)
    result = ask(page, "How can I improve my spending?").json()
    assert result["coverage"]["record_count"] == 240
    expect(page.locator("#txn-coverage")).to_contain_text("240 available records")
    expect(page.locator("#txn-conversation b")).to_have_count(0)
    ask(page, "I can repay 10k to 15k monthly")
    assert payloads[-1]["history"][0]["question"] == "How can I improve my spending?"
    expect(page.locator("#txn-conversation p")).to_have_count(2)
    page.locator("#txn-new-conversation").click()
    expect(page.locator("#txn-conversation p")).to_have_count(0)
    ask(page, "New question")
    assert "history" not in payloads[-1]


def test_original_summary_and_direct_answer_still_work(page):
    page.goto(FRONTEND + "/transactions")
    result = ask(page, "What is my total spend?").json()
    assert result["mode"] == "direct" and result["answer"] == "Original flow answer."
    page.locator("#txn-summary-button").click()
    expect(page.locator("#txn-ai-response-text")).to_have_text("Original flow answer.")
    expect(page.locator("#txn-coverage")).to_be_empty()


def test_failure_recovers_and_pagination_terminates(page):
    page.goto(FRONTEND + "/transactions")
    assert ask(page, "fail").status == 503
    expect(page.locator("#txn-ai-response-text")).to_contain_text("temporarily unavailable")
    expect(page.locator("#txn-new-conversation")).to_be_enabled()
    assert ask(page, "Advice please").status == 200
    for index in range(11):
        page.locator("#txn-load-more").click()
        expect(page.locator("#table tr")).to_have_count((index + 2) * 20 + 1)
    page.locator("#txn-load-more").click()
    expect(page.locator("#txn-load-more")).to_be_disabled()
    expect(page.locator("#txn-load-status")).to_have_text("No more transactions.")


def test_loan_scope_and_navigation_clear_conversation(page):
    page.goto(FRONTEND + "/loan-details?id=LOAN002")
    expect(page.locator("#payment-history tr")).to_have_count(19)
    result = ask(page, "How is my car-loan history?", "loan").json()
    assert result["coverage"]["record_count"] == 55
    expect(page.locator("#loan-conversation p")).to_have_count(1)
    page.goto(FRONTEND + "/loan-details?id=LOAN003")
    expect(page.locator("#loan-conversation p")).to_have_count(0)
    assert ask(page, "How is this history?", "loan").json()["coverage"]["record_count"] == 80
    page.reload()
    expect(page.locator("#loan-conversation p")).to_have_count(0)
    page.goto(FRONTEND + "/loan-details#id=LOAN001")
    expect(page.locator("#loan-title")).to_contain_text("Personal Loan")
    page.evaluate("location.hash = 'id=LOAN004'")
    expect(page.locator("#loan-title")).to_contain_text("Education Loan")
    expect(page.locator("#loan-conversation p")).to_have_count(0)


@pytest.mark.skipif(os.getenv("RUN_LIVE_INSIGHTS") != "1", reason="Opt-in Gemini verification")
def test_live_insights_followup_through_widget(page):
    page.goto(FRONTEND + "/loan-details?id=LOAN002")
    first = ask(page, "Based on this loan's full history, what could I improve before applying for another car loan?", "loan")
    assert first.status == 200
    assert first.json()["mode"] == "insights" and first.json()["coverage"]["record_count"] == 55
    second = ask(page, "Estimate EMI for a 5 lakh car loan over 5 years. Ask me for any missing assumptions.", "loan")
    assert second.status == 200 and "rate" in second.json()["answer"].lower()
    third = ask(page, "Use annual interest of 8% to 12%.", "loan")
    assert third.status == 200
    assert "10,138.20–11,122.22" in third.json()["answer"]
    expect(page.locator("#loan-conversation p")).to_have_count(3)
    artifact = os.getenv("BROWSER_ARTIFACTS")
    if artifact:
        from pathlib import Path
        Path(artifact).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(artifact) / "live-insights.png"), full_page=True)
