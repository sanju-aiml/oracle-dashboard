# ORACLE AI: market answers, forecasts, 24/7 paper bot, phone alerts

## Run it (Windows / Antigravity terminal)
```
pip install -r requirements.txt
python seed_history.py          # ONCE, while online: downloads history into your own database
python train.py                 # trains + validates every asset (CPU is enough; ~1-3 min per 10 assets)
python train.py --images        # optional: chart-image model
uvicorn main:app --host 127.0.0.1 --port 8000
```
Open http://127.0.0.1:8000 for the demo page. Run `pytest tests/test_all.py` any time (17 tests).
Progress of training is written line by line to `gate_log.jsonl`.

## Phone alerts (free)
1. Install the free **ntfy** app, subscribe to a long random topic, e.g. `oracle-sanju-7f3k29dq`.
2. `POST /api/alerts/channel {"user_id":"sanju","ntfy_topic":"oracle-sanju-7f3k29dq"}` (same for your mother with her own topic).
3. `POST /api/alerts/test?user_id=sanju` and check the phone.
4. Add rules: `POST /api/alerts/rules {"user_id":"sanju","symbol":"RELIANCE","kind":"price_below","threshold":2400}`
   kinds: price_below, price_above, drop_from_high, rise_day, fall_day, rsi_below, rsi_above, near_52w_low.
5. Add holdings so you get told when a stock hits YOUR stop or target:
   `POST /api/holdings {"user_id":"sanju","symbol":"TCS","qty":10,"avg_price":2500,"stop_pct":8,"target_pct":15}`
6. IPOs: `POST /api/admin/ipos` (header X-Admin-Token) with open/close dates; alerts come the day before, on opening day and on the last day.
Telegram also works: set `TELEGRAM_BOT_TOKEN`, then pass `telegram_chat_id`.

## Live price without refreshing
`GET /api/stream/NIFTY?interval=5` is a Server-Sent Events stream (demo.html shows it). Every viewer shares one stored price per symbol,
so 1000 viewers do not mean 1000 calls to the data sources. Each event carries price, status (fresh/backup/stale), market (open/closed), source, age.
Source order per asset: crypto APIs / Yahoo / Stooq / Finnhub -> NSE website and Google Finance (web, robots.txt checked) -> last stored price.
For truly real-time NSE ticks use your broker API (Upstox / Angel One / Zerodha); that is what Google and Groww themselves license.

## Keep it running 24/7
`docker run -d --restart always -p 8000:8000 -v oracle_data:/data -e ORACLE_ADMIN_TOKEN=... oracle`
or on Windows keep the laptop plugged in (sleep = Never) or move to a cheap always-on server.
The bot loop never dies on a bad data source; it logs, backs off and continues.

## Environment variables
ORACLE_ADMIN_TOKEN (protects /api/admin/*), FINNHUB_KEY (free key, better US quotes), ALLOW_SCRAPING=0/1,
BOT_SYMBOLS=BTC,XAU,NIFTY,..., PAPER_START, TELEGRAM_BOT_TOKEN, NTFY_SERVER.

## What is guaranteed and what is not
- Guaranteed by design: a price is never invented. Every number carries source, time and a fresh/backup/stale label.
  If all live sources are down, answers use the last stored price and say so.
- NOT guaranteed: profit, or knowing the future. Forecasts are probabilities. A model "passes" only if it beats
  a coin on the newest 20% of history it never saw (p < 0.02, AUC >= 0.52, profitable after costs). Most assets
  will NOT pass, and then ORACLE says "no proven edge" and the bot does not trade that asset.
- The bot is PAPER only (virtual money). Prove it for 2-3 months in /api/bot/status before risking real money,
  and even then risk only what you can afford to lose.
- Alerts are information, not advice. A falling market is not automatically a buying chance.

## Files
config.py (assets, limits) · store.py (SQLite) · market_data.py (fallback chain, robots.txt-respecting web backup)
features.py · model.py (walk-forward + holdout gate) · image_model.py (chart screenshots) · bot.py (paper bot, UP/DOWN resolver)
alerts.py + notify.py (phone alerts) · answer.py (question answering) · routes.py (API) · main.py · demo.html
