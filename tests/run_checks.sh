#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export ENABLE_INSIGHTS=false
export E2E_IN_PROCESS=1
export BROWSER_CHANNEL="${BROWSER_CHANNEL:-chrome}"
embedded-agent-be/.venv/bin/python -m pytest -c embedded-agent-be/pytest.ini embedded-agent-be/tests -q
embedded-agent-be/.venv/bin/python -m pytest tests/test_browser.py tests/test_insights_browser.py tests/test_explain_browser.py -q
