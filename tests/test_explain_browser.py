import os

import pytest
from playwright.sync_api import expect, sync_playwright

from browser_harness import attach
import explain

FRONTEND = "http://explain.test"
API = "http://api.explain.test"
SECTIONS = [("/", "dashboard.credit_score"), ("/", "dashboard.top_transactions"), ("/", "dashboard.active_loans"),
            ("/credit", "credit.current_score"), ("/credit", "credit.score_trend"), ("/credit", "credit.factors"), ("/credit", "credit.breakdown")]


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setenv("ENABLE_INSIGHTS", "true")
    calls = []
    def generate(context):
        calls.append(context)
        return explain.Explanation(meaning="Meaning of " + context["section"], key_points=["<b>Literal financial text</b>"], takeaways=["Only this section is included."])
    monkeypatch.setattr(explain, "generate_explanation", generate)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv("BROWSER_CHANNEL", "chrome"), headless=os.getenv("RUN_NATIVE_SPEECH") != "1")
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.explain_calls = calls
        page.set_default_timeout(15000)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        client = attach(page, FRONTEND, API)
        yield page
        client.close()
        context.close()
        browser.close()
        assert not errors


def button(page, section):
    return page.locator(f'[data-explain="{section}"]')


def panel(page, section):
    return page.locator('#explain-' + section.replace('.', '-'))


@pytest.mark.parametrize("flag", ["true", "false"])
@pytest.mark.parametrize("path,section", SECTIONS)
def test_all_seven_buttons_with_either_insights_setting(page, monkeypatch, flag, path, section):
    monkeypatch.setenv("ENABLE_INSIGHTS", flag)
    page.goto(FRONTEND + path)
    expect(button(page, section)).to_be_enabled()
    button(page, section).focus()
    page.keyboard.press("Enter")
    expect(panel(page, section)).to_contain_text("Meaning of " + section)
    expect(panel(page, section).locator("b")).to_have_count(0)
    assert page.explain_calls[-1]["section"] == section
    assert len(page.explain_calls) == 1
    button(page, section).click()
    expect(panel(page, section)).to_be_hidden()
    button(page, section).click()
    expect(panel(page, section)).to_be_visible()
    assert len(page.explain_calls) == 1


def test_dashboard_context_excludes_hidden_fields_and_closed_loans(page):
    payloads = []
    page.on("request", lambda request: payloads.append(request.post_data_json) if request.url.endswith('/sections/explain') else None)
    page.goto(FRONTEND)
    expect(page.locator('#loanCards .section-loan-card')).to_have_count(3)
    expect(page.locator('#loanCards')).not_to_contain_text('Education Loan')
    for section in ['dashboard.credit_score', 'dashboard.top_transactions', 'dashboard.active_loans']:
        button(page, section).click()
        expect(panel(page, section)).to_contain_text('Meaning of')
    assert set(payloads[0]['snapshot']) == {'score', 'change', 'refreshed'}
    assert payloads[0]['snapshot']['score'] == int(page.locator('#score').inner_text())
    assert all(set(row) == {'date', 'category', 'type', 'amount'} for row in payloads[1]['snapshot']['rows'])
    assert all('id' not in loan and 'original_amount' not in loan for loan in payloads[2]['snapshot']['loans'])
    assert page.explain_calls[-1]['calculated']['loan_count'] == 3


def test_independent_loading_empty_sections_and_safe_source_strings(page):
    page.route(API + '/credit/summary', lambda route: route.fulfill(status=503, json={'detail': 'Unavailable'}))
    page.route(API + '/transactions/top', lambda route: route.fulfill(json=[]))
    page.goto(FRONTEND)
    expect(button(page, 'dashboard.credit_score')).to_be_disabled()
    expect(page.locator('.section-data-status').nth(0)).to_contain_text('could not load')
    expect(button(page, 'dashboard.top_transactions')).to_be_disabled()
    expect(page.locator('.section-data-status').nth(1)).to_contain_text('No data')
    expect(button(page, 'dashboard.active_loans')).to_be_enabled()
    page.route(API + '/credit/details', lambda route: route.fulfill(json={
        'reasons': ['<img src=x onerror=alert(1)>'], 'breakdown': [{'label': '<b>Factor</b>', 'percent': 35}]}))
    page.goto(FRONTEND + '/credit')
    expect(button(page, 'credit.current_score')).to_be_disabled()
    expect(button(page, 'credit.score_trend')).to_be_enabled()
    expect(button(page, 'credit.factors')).to_be_enabled()
    expect(page.locator('#reasons img')).to_have_count(0)
    expect(page.locator('#score-breakdown b')).to_have_count(0)


def test_error_retry_and_changed_snapshot_invalidates_cache(page):
    attempts = []
    def respond(route):
        attempts.append(route.request.post_data_json)
        if len(attempts) == 1:
            route.fulfill(status=503, json={'detail': 'Temporarily unavailable'})
        else:
            route.fallback()
    page.route(API + '/sections/explain', respond)
    page.goto(FRONTEND)
    section = 'dashboard.credit_score'
    button(page, section).click()
    expect(panel(page, section)).to_contain_text('Temporarily unavailable')
    panel(page, section).get_by_role('button', name='Retry explanation').click()
    expect(panel(page, section)).to_contain_text('Meaning of')
    assert len(attempts) == 2
    page.evaluate("sectionExplanations['dashboard.credit_score'].setSnapshot({score: 750, change: 20, refreshed: 'Now'})")
    expect(panel(page, section)).to_be_hidden()
    button(page, section).click()
    expect(panel(page, section)).to_contain_text('Meaning of')
    assert len(attempts) == 3 and attempts[-1]['snapshot']['score'] == 750


def test_closing_aborts_pending_fetch_and_discards_stale_response(page):
    pending = []
    page.route(API + '/sections/explain', lambda route: pending.append(route))
    page.goto(FRONTEND)
    section = 'dashboard.credit_score'
    button(page, section).click()
    expect(panel(page, section)).to_contain_text('Explaining this section')
    page.wait_for_function("sectionExplanations['dashboard.credit_score'].controller !== null")
    assert len(pending) == 1
    button(page, section).click()
    expect(panel(page, section)).to_be_hidden()
    assert page.evaluate("sectionExplanations['dashboard.credit_score'].controller === null")
    pending[0].fulfill(json={'section': section, 'meaning': 'Stale response', 'key_points': ['x'], 'takeaways': ['y']})
    assert page.evaluate("sectionExplanations['dashboard.credit_score'].cache === null")
    page.unroute(API + '/sections/explain')
    button(page, section).click()
    expect(panel(page, section)).to_contain_text('Meaning of')


def test_empty_and_single_point_chart(page):
    page.route(API + '/credit/history', lambda route: route.fulfill(json={'history': []}))
    page.goto(FRONTEND + '/credit')
    expect(button(page, 'credit.score_trend')).to_be_disabled()
    expect(page.locator('#score-chart')).to_have_attribute('aria-label', 'No score history available')
    page.unroute(API + '/credit/history')
    page.route(API + '/credit/history', lambda route: route.fulfill(json={'history': [{'date': '2026-09-01', 'score': 700}]}))
    page.reload()
    expect(button(page, 'credit.score_trend')).to_be_enabled()
    button(page, 'credit.score_trend').click()
    expect(panel(page, 'credit.score_trend')).to_contain_text('Meaning of')
    assert page.explain_calls[-1]['calculated']['change_points'] == 0


SPEECH_STUB = """(() => {
  window.speechLog = {spoken: [], cancelled: 0};
  window.SpeechSynthesisUtterance = class {constructor(text) {this.text = text;}};
  Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: {
    getVoices: () => [{name: 'English', lang: 'en-US'}, {name: 'India', lang: 'en-IN'}],
    cancel: () => window.speechLog.cancelled++,
    speak: utterance => {window.speechLog.spoken.push(utterance.text); window.lastUtterance = utterance;}
  }});
})()"""


def test_audio_controls_exact_text_single_playback_and_errors(page):
    page.add_init_script(SPEECH_STUB)
    page.goto(FRONTEND)
    for section in ['dashboard.credit_score', 'dashboard.top_transactions']:
        button(page, section).click()
        expect(panel(page, section)).to_contain_text('Meaning of')
    assert page.evaluate('speechLog.spoken.length') == 0
    first = panel(page, 'dashboard.credit_score')
    second = panel(page, 'dashboard.top_transactions')
    first.get_by_role('button', name='Read aloud').click()
    expect(first.get_by_role('button', name='Stop', exact=True)).to_be_enabled()
    assert page.evaluate('lastUtterance.voice.lang') == 'en-IN'
    assert 'Meaning of dashboard.credit_score' in page.evaluate('speechLog.spoken[0]')
    second.get_by_role('button', name='Read aloud').click()
    expect(first.get_by_role('button', name='Stop', exact=True)).to_be_disabled()
    expect(first.get_by_role('button', name='Read aloud')).to_be_enabled()
    page.evaluate("lastUtterance.onerror({error: 'synthesis-failed'})")
    expect(second).to_contain_text('Audio could not play')
    second.get_by_role('button', name='Read aloud').click()
    second.get_by_role('button', name='Stop', exact=True).click()
    expect(second).to_contain_text('Stopped.')
    second.get_by_role('button', name='Read aloud').click()
    button(page, 'dashboard.top_transactions').click()
    assert page.evaluate('SectionSpeech.owner === null')


def test_audio_unavailable_keeps_text(page):
    page.add_init_script("Object.defineProperty(window, 'speechSynthesis', {value: undefined}); delete window.SpeechSynthesisUtterance;")
    page.goto(FRONTEND)
    button(page, 'dashboard.credit_score').click()
    expect(panel(page, 'dashboard.credit_score')).to_contain_text('Meaning of')
    expect(panel(page, 'dashboard.credit_score').get_by_role('button', name='Read aloud')).to_be_disabled()
    expect(panel(page, 'dashboard.credit_score')).to_contain_text('unavailable in this browser')


@pytest.mark.skipif(os.getenv('RUN_NATIVE_SPEECH') != '1', reason='Opt-in: real system speech in headed Chrome')
def test_native_read_aloud_completes(page):
    page.goto(FRONTEND)
    button(page, 'dashboard.credit_score').click()
    output = panel(page, 'dashboard.credit_score')
    expect(output).to_contain_text('Meaning of')
    page.wait_for_function('window.speechSynthesis.getVoices().some(voice => /^en\\b/i.test(voice.lang))', timeout=15000)
    output.get_by_role('button', name='Read aloud').click()
    expect(output).to_contain_text('Finished reading.', timeout=45000)
    expect(output.get_by_role('button', name='Read aloud')).to_be_enabled()
