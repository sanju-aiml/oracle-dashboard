# Prompt for the Antigravity agent (paste everything below the line)

---

The folder `oracle_ai/` (next to this file) is a tested market-intelligence backend. Integrate it into my ORACLE app
at 127.0.0.1:8000 and finish the setup. Do not rewrite its modules; call them. Work until each step is verified and
report only what you ran and its output.

1. Setup: create a venv, `pip install -r oracle_ai/requirements.txt`, run `pytest oracle_ai/tests/test_all.py` and confirm all pass.
2. Data: run `python seed_history.py` (needs internet). Report any symbol with candles=0 and fix its source/ticker in config.py
   (NSE stocks use Yahoo tickers like RELIANCE.NS). Add the Indian stocks I care about to config.ASSETS.
3. Train: run `python train.py`, then `python train.py --images`. Use CPU unless a CUDA GPU is present. Show me the
   PASS/FAIL table from gate_log.jsonl. Do NOT loosen the gate (GATE_ALPHA, GATE_MIN_AUC, holdout) to make models pass and do
   NOT retrain repeatedly until something passes; a FAIL is a valid honest result.
4. Integrate into the existing ORACLE FastAPI app: `app.include_router(routes.router)` and start `bot.run_forever` in its lifespan
   (or run `run_bot.py` as a separate process). Fix the frontend 404 by pointing the Paper Trading panel to GET /api/market/paper-trade,
   map its fields (equity, cash, return_pct, open_positions, recent_closed, win_rate, halted) to the existing elements, and null-check every
   element before setting textContent.
5. Chatbot: replace the "Fallback mode: AI model offline" path with POST /api/ask. Show the answer text as returned. Keep the
   fresh/backup/stale wording and the disclaimer. Remove any "zero hallucinations" claim from the UI.
6. UI features to add (match the current design, UTF-8 so icons render):
   - UP / DOWN buttons per symbol with duration picker (5m, 15m, 1h, 1d) -> POST /api/play/call; show locked entry price and, after
     resolution, win/loss and pnl_pct from GET /api/play/history. Use a persistent random user_id from localStorage.
   - Chart image upload with a consent checkbox -> POST /api/chart/analyze; show the returned message; pass image_token to /api/play/call.
   - Alerts screen: add rule (symbol, kind from GET /api/alerts/kinds, threshold), list/delete rules, holdings form (qty, avg price, stop %, target %),
     notification setup (ntfy topic, with a "Send test" button -> POST /api/alerts/test), alert history from GET /api/alerts/log, IPO list from GET /api/ipos.
   - Market stress is automatic; no UI needed.
7. Terms: show the Terms checkbox at signup (store acceptance with version and time), footer line "Educational only, not financial advice",
   and the Tele-MANAS 14416 support line from the Terms doc.
8. 24/7: run under a process manager or Docker with restart always; confirm GET /api/bot/status shows last_tick advancing every minute and
   last_error null. Keep the laptop plugged in with sleep set to Never if running locally.
9. Live updates like Google/Groww: for every price card (indices, my stocks, crypto, gold, oil) subscribe with
   `new EventSource('/api/stream/<SYMBOL>?interval=5')` and update the number, % change, status badge (fresh/backup/stale),
   "market closed" badge, source and "x s ago" on every event, no page refresh. Close the EventSource when the card is not visible.
   Show "Market closed: last traded price" when q.market == "closed", exactly like Google's "Closed: Oct 22".
10. Web backup for Indian stocks: market_data.py already has an NSE-website fallback (obeys robots.txt) after Yahoo. Test it on THIS machine for
   NIFTY, RELIANCE, TCS. If NSE blocks it or robots.txt disallows it, do not bypass: instead add Upstox or Angel One SmartAPI (my broker
   account, free for account holders) as the FIRST quote source for NSE/BSE symbols, with keys read from environment variables only.
   Report which source each symbol actually uses.
11. Verify end to end with real data: ask "bitcoin future", "gold", "crude oil", "natural gas", "nifty", "RELIANCE.NS"; unplug the internet and
   ask again (answers must use stored data and say "last stored price"); send a test alert to my phone; place an UP call and watch it resolve.

Never: invent prices, hide stale data, promise profit, enable real-money trading, or commit API keys.
