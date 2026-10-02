# Explain sections

All seven existing Explain buttons now work: Credit Score, Top Transactions and Top Active Loans on the dashboard; Current Score, Score Trend, Factors Affecting Your Score and Score Breakdown on Credit Details.

Click Explain to open a panel directly beneath the section heading and button, above its data, with **What this means**, **Your information** and **Points to notice**. The section data moves down while the panel is open; Hide explanation removes the panel from the layout and restores the original position. Read aloud is optional and never starts automatically. Stop, closing the panel, leaving the page, or starting another section's audio stops playback.

## Run and configuration

Use the existing backend and frontend commands. Explain is always available and works whether `ENABLE_INSIGHTS` is true or false. The currently running development frontend uses port 3001 because an unrelated Docker service occupies port 3000; the backend remains on port 8000.

The backend uses the existing `GOOGLE_APPLICATION_CREDENTIALS` and Vertex client. `EXPLAIN_MODEL` defaults to `gemini-3.5-flash-lite`. Each uncached explanation makes one structured generation call, without the insights classifier or any history retrieval. The provider deadline is 30 seconds with one transport attempt and an output cap of 3,072 tokens. Gemini 3 models use LOW thinking. Initial credential acquisition is separate from the provider HTTP deadline. The browser stops waiting after 45 seconds; closing a panel aborts its browser request, but cannot guarantee cancellation of an already-running provider call.

## API and boundaries

`POST /sections/explain` accepts `{section, snapshot}` and returns `{section, meaning, key_points, takeaways}`. Section IDs and their snapshot fields are:

| Section | Snapshot |
| --- | --- |
| `dashboard.credit_score` | `score`, `change`, `refreshed` |
| `dashboard.top_transactions` | `rows`: `date`, `category`, `type`, `amount` |
| `dashboard.active_loans` | `loans`: `name`, `type`, `outstanding`, `emi`, `interest_rate`, `next_due_date`, `tenure_remaining`, `percent_paid` |
| `credit.current_score` | Dashboard score fields plus `previous_score`, `range_min=300`, `range_max=850` |
| `credit.score_trend` | `history`: `date`, `score` |
| `credit.factors` | `reasons`: displayed labels |
| `credit.breakdown` | `breakdown`: `label`, `percent` |

The frontend retains the structured values it renders, including the data used to draw the chart. It does not scrape HTML or refetch data for an explanation. Backend discriminated schemas select and validate the corresponding snapshot; unexpected fields are excluded. Internal loan/transaction IDs, hidden merchant fields, raw original loan amounts and other sections are not sent to the model. General term definitions are permitted, while personal observations must be supported by the clicked section.

Python computes displayed debit and credit totals, net flow, active-loan balance and EMI totals, and chart extrema and point changes. Decimal summation avoids introducing floating-point artifacts in monetary totals. The dashboard now filters its loan cards to Active accounts, matching the section heading. Its displayed repayment percentage is calculated from the same source values as the progress bar.

Malformed requests return HTTP 422. Empty sections return HTTP 400 and are disabled in the UI. Provider errors, invalid outputs, blank explanations and non-normal completions return a generic HTTP 503 with a retry action. Errors never become a fabricated explanation. Logs contain section IDs, timing, token counts and exception type, not source records or generated text.

Factor labels are qualitative, not measurements. The prompt forbids echoing instruction-like labels, interpreting them as account facts or inventing numeric thresholds; a code check additionally rejects numerical factor explanations. Score-breakdown percentages are described as the demo's displayed weights, not a verified credit-bureau formula. Generated prose still relies on model grounding; these checks are not a universal claim verifier. Browser snapshots have the same prototype trust assumption as the original direct assistant and are not authenticated customer records.

A small server-owned glossary supplies plain meanings only for recognized terms actually present in the clicked factor/breakdown section. Its educational distinction between payment history and credit enquiries follows [CIBIL's explanation of accounts and enquiries](https://www.cibil.com/blog/walk-through-reading-accounts-enquiries-sections-in-your-cibil-report). It does not import another page's records or claim the demo uses CIBIL's score scale or formula.

## UI and speech

Sections load independently. A failed credit request does not block the transactions/loans cards, and a failed chart does not block the factor sections. Empty and single-point charts are handled without invalid coordinates. Source values and explanations use safe DOM text rendering.

Each section keeps only its latest successful explanation in page memory. Reopening it reuses the result; replacing the snapshot invalidates it. Closing the panel or updating its data aborts the browser request and invalidates stale callbacks. Nothing is written to localStorage or conversation history.

Speech uses the browser's native speech-synthesis API. It prefers an English-India voice, then another English voice, then the browser-selected voice for English-India. Availability and pronunciation vary by OS/browser. Text is split into short utterances to avoid long-reading cutoffs. One speech owner and a generation counter prevent cancelled utterance callbacks from interfering with another section. Unsupported or failed audio leaves the text usable and presents a specific audio message. Panels support keyboard activation, expanded/collapsed semantics, and status announcements.

## Verification

From the repository root, `bash tests/run_checks.sh` runs the existing suites plus the new explanation tests. It uses the actual frontend files and FastAPI handlers through the isolated browser harness, with deterministic model outputs. It requires the documented development dependencies and installed Chrome.

Live model checks (eight provider calls: seven section fixtures and one instruction-like label):

```bash
cd embedded-agent-be
GOOGLE_APPLICATION_CREDENTIALS=../../creds.json RUN_LIVE_EXPLAIN=1 .venv/bin/python -m pytest tests/test_explain_live.py -q
```

Native audio verification in an isolated visible Chrome window (briefly plays a synthetic explanation), from the repository root:

```bash
RUN_NATIVE_SPEECH=1 embedded-agent-be/.venv/bin/python -m pytest tests/test_explain_browser.py -q -k native_read
```

Real HTTP/browser/Gemini smoke test for all seven buttons, with the servers already running:

```bash
RUN_EXPLAIN_SMOKE=1 embedded-agent-be/.venv/bin/python -m pytest tests/test_explain_running_app.py -q
```

`FRONTEND_URL` can override the smoke test's default `http://127.0.0.1:3001`. Screenshots go to `/tmp/goodscore-explain-artifacts` unless `BROWSER_ARTIFACTS` is set. Live provider checks consume model quota.

Validation on 2 October 2026: 79 deterministic backend cases and 29 deterministic browser cases passed. All seven live section cases and the adversarial-label case passed. Native Chrome speech completed successfully through the real system voice, with UI controls restored after completion. The actual running-app smoke test also passed all seven buttons, and the captured dashboard and Credit Details panels were visually inspected. Earlier testing caught and fixed an unsupported-audio cleanup error and a model echo of an instruction-like factor label; a scoped glossary was added to improve terminology explanations.
