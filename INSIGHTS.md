# Optional intelligent insights

This feature adds advice, analysis, broader-history questions and illustrative loan scenarios to the existing Ask widgets. The original page-only answer generator and both Summarize endpoints remain in use. This intentionally extends the original take-home's page-only requirement when enabled.

## Run

From `embedded-agent-be`, activate the existing environment and start the backend:

```bash
source .venv/bin/activate
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/../../creds.json"
export ENABLE_INSIGHTS=true
uvicorn server:app --reload
```

Start the frontend with `./start.sh` from `embedded-agent-fe`. Reload pages after restarting with a different feature setting. With `ENABLE_INSIGHTS` unset or false, the original model path and random demo APIs are used; no router call is made. Credentials are still loaded lazily.

| Setting | Default | Purpose |
| --- | --- | --- |
| `ENABLE_INSIGHTS` | `false` | Opt into routing and stable demo data |
| `ROUTER_MODEL` | `gemini-3.5-flash-lite` | Classification and extraction of user-supplied scenario inputs |
| `INSIGHTS_MODEL` | `GEMINI_MODEL`, otherwise `gemini-3.5-flash` | New reasoning path |
| `ROUTER_TIMEOUT_SECONDS` | `15` | Router HTTP deadline |
| `INSIGHTS_TIMEOUT_SECONDS` | `60` | Insights HTTP deadline |

Both models reuse the existing Vertex client and account. New calls use structured output, disabled automatic function calling, and one transport attempt. Gemini 3 models use MINIMAL thinking for routing and LOW for insights, with output caps of 2,048 and 4,096 tokens respectively. Truncated/non-normal completions are rejected rather than displayed. Existing direct-generation settings are unchanged. Deadlines are per provider HTTP request; initial credential acquisition is separate. A provider failure returns HTTP 503 and restores UI controls; it does not silently invoke a different answer path.

## Behavior

| Example | Behavior |
| --- | --- |
| “What is my total spend?” | Existing direct flow, loaded rows only |
| “What is my credit score?” on Transactions | Existing refusal; unavailable facts do not become personal guesses |
| “How could I improve my spending habits?” | Insights using all available transaction history |
| “Sum my spending across all history, including older rows.” | New history path, even though the result is factual |
| “Suggest savings using only these displayed rows.” | Insights restricted to the displayed snapshot |
| “Based on this loan's history, how could I improve my credit score?” | Evidence-based suggestions using only the selected loan account |
| “What is my EMI, and how could I reduce budget pressure?” | Insights answers both factual and advisory parts |
| “Estimate EMI for 5 lakh over 5 years.” | Explains what is available and asks for explicit interest assumptions |
| Follow-up: “Use annual rates of 8% to 12%.” | Python computes INR 10,138.20–11,122.22 monthly; response shows assumptions |

The router sees the current question, page type and recent conversation, not full financial history. Its structured decision selects direct/insights and displayed/history scope, optionally a requested date interval. The backend owns retrieval. A loan request supplies the selected account ID through the existing validated request, never through a model tool or inferred account selector.

General financial reasoning is permitted only in the insights prompt. Personal observations must come from the scoped records or user-reported assumptions. Cash inflows are not automatically salary, net cash flow is not automatically disposable income, and missing payments/values cannot be reconstructed from placeholders. Recorded payment behavior can inform suggestions, but these are not credit-score forecasts or lender decisions. Responses should identify missing evidence rather than promise a loan amount.

## Stable demo data

The enabled feature uses one synthetic, fixed dataset as of **1 October 2026** (`demo-2026-09-v1`):

- 240 transactions across April–September 2026, served in stable pages of 20. Page 12 is empty. The top-transactions widget uses the same records.
- Five existing loan IDs with consistent overview values and payment schedules. Loan Details returns the newest 18 installments; the insights repository retrieves the full available schedule for that exact account.
- The same loan repository supplies the dashboard/list summaries. Credit-page APIs remain starter demo data and are never accessed by insights.

“Complete” means complete available demo records, not the customer's financial lifetime. Responses include source, dates, counts, requested period and completeness metadata. Explicitly filtered loan payment rows do not change lifetime overview totals. There is no connection to a bank, credit bureau, live-rate feed or real customer database.

## Scenario calculations

The router extracts explicitly supplied principal, annual-rate bounds, tenure in months, or monthly repayment-budget bounds, with exact quotes from user turns. The calculator checks that quoted values occur in user text (supporting INR k/lakh/crore and years-to-months), validates domain/range limits, and performs the amortization in Python. Prior assistant text cannot supply a scenario assumption.

- EMI: fixed principal and tenure, low/high annual rates.
- Affordable principal: low/high repayment budgets, fixed tenure and low/high annual rates; the lower principal uses the smaller budget and higher rate.
- Zero interest uses principal divided by months. Positive fixed rates use the standard annuity formula. Results round to two decimal places.
- Rates must be 0–100%, tenure a whole number of 1–600 months, principal/budgets positive, and range bounds ordered. Inputs are bounded to INR 10 billion.
- Missing/invalid inputs produce a server-rendered follow-up for the needed assumptions rather than a numerical guess or model-suggested rate example. Identical supplied bounds produce the same endpoint twice; uncertainty is not manufactured.
- Estimates exclude fees/insurance and assume equal monthly payments and fixed interest. The server appends the calculated range and assumptions. They are affordability illustrations, never approval or eligibility predictions.

The quote check detects absent or fabricated numbers; semantic interpretation and correction of user statements still depend on the router. Generated observations are prompt-grounded, not independently verified claim by claim. Existing snapshot authenticity assumptions also remain for the original direct flow and explicitly displayed-only analysis.

## API and conversation

The four existing POST paths remain. Summary payloads and responses are unchanged. Ask requests optionally accept `history`, a list of `{question, answer}` exchanges. It is limited to 10 exchanges and 30,000 combined characters, with each question limited to 1,000 and each answer to 12,000 characters.

With insights enabled, Ask responses retain `answer` and add `mode` (`direct` or `insights`) and `coverage`. With the flag off, the original `{answer}` response is returned. `GET /assistant/config` exposes only `insights_enabled` so the widgets can adapt.

Conversation lives in browser memory, bound to the page and selected loan. New conversation, reload, navigation and account changes clear it. Summaries do not enter conversation history. Load More updates the displayed snapshot; direct answers continue using the current rows. Earlier assistant text is supplied for reference resolution but never establishes financial facts. A self-contained new question takes precedence over an old scenario.

Text uses safe DOM text rendering. New conversation is disabled during a request. Failures are not appended to conversation history. Older backends without `/assistant/config` retain the original widget behavior.

## Repeatable checks

From the repository root:

```bash
embedded-agent-be/.venv/bin/python -m pip install -r embedded-agent-be/requirements-dev.txt
bash tests/run_checks.sh
```

The browser harness uses isolated headless Chrome and actual frontend files plus actual FastAPI handlers, connected by Playwright's intercepted HTTP transport. It does not require or interfere with servers on ports 3000/8000. New deterministic browser tests stub only model outputs; original browser tests retain their existing fixture/stub behavior. No real provider request is made by default.

For live classification, API and conversational browser checks with synthetic data:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/../creds.json"
RUN_LIVE_INSIGHTS=1 bash tests/run_checks.sh
```

Live insights checks make up to 21 model calls and consume provider quota. They cover direct/refusal/advisory/broader-history routing, input corrections, personal suggestions, deterministic ranges, and a three-turn loan scenario. To include the original 12-call live acceptance case, also set `RUN_LIVE_GEMINI=1`.

Logs include stage, route, scope, record count, latency, token counts and exception type, without logging questions, records, answers or credential contents. This is a single synthetic customer prototype, not a multi-user authorization system. Production integration must replace the repository with an authenticated, versioned data source before real customer history is exposed.

## Verification recorded on 2 October 2026

- 41 deterministic backend cases passed, including all 16 original cases.
- 8 deterministic browser cases passed in isolated headless Chrome, including all 4 original cases.
- 12 opt-in live backend cases passed against Gemini: 10 routing categories, a corrected-input follow-up, and an API case exercising personalized advice and a calculated principal range.
- The opt-in live browser case passed a three-turn car-loan conversation: full-history advice, a request with missing interest assumptions, and a follow-up producing the independently checked EMI range.
- Captured browser output was visually inspected. UTF-8 rendering and conversation state were checked; the original `agent.py` was verified byte-for-byte against the submission archive.

An initial live structured-output validation failure led to explicit thinking/output limits and rejection of non-normal completions. Subsequent live API and browser checks passed. These finite checks demonstrate the tested scenarios, not guaranteed model behavior on every question. The optional original 12-request live suite was not rerun as part of this change; its deterministic regression cases passed.
