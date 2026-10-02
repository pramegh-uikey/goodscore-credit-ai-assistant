"""Optional real HTTP + Gemini smoke test against already-running servers."""
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(os.getenv('RUN_EXPLAIN_SMOKE') != '1', reason='Requires running frontend/backend and Gemini')


def test_all_explain_buttons_on_running_app():
    frontend = os.getenv('FRONTEND_URL', 'http://127.0.0.1:3001')
    artifacts = Path(os.getenv('BROWSER_ARTIFACTS', '/tmp/goodscore-explain-artifacts'))
    artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('BROWSER_CHANNEL', 'chrome'))
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        for path, count, filename in [('/', 3, 'dashboard'), ('/credit', 4, 'credit')]:
            page.goto(frontend + path)
            buttons = page.locator('[data-explain]')
            expect(buttons).to_have_count(count)
            for index in range(count):
                button = buttons.nth(index)
                expect(button).to_be_enabled()
                section = button.get_attribute('data-explain')
                with page.expect_response(lambda response: response.url.endswith('/sections/explain'), timeout=60000) as pending:
                    button.click()
                response = pending.value
                assert response.status == 200, response.text()
                assert response.json()['section'] == section
                panel = page.locator('#explain-' + section.replace('.', '-'))
                expect(panel).to_contain_text('What this means')
                expect(panel.get_by_role('button', name='Read aloud')).to_be_enabled()
            page.screenshot(path=str(artifacts / (filename + '.png')), full_page=True)
        browser.close()
        assert not errors
