You are continuing a working MVP called ORACLE (this repo). Read README.md, core.py, server.py, static/index.html and tests/ first. Run `python -m unittest discover -s tests -v`; all tests must stay green after every step.

Goal: grow it into a production-ready AI business prediction and decision-intelligence SaaS plus a personal-finance and markets workspace (India-first, global-ready), following the ORACLE blueprint dated 21 Oct 2026.

Non-negotiable rules
1. Never fabricate data. Every number carries kind = actual | calculated | estimate | forecast. If a provider key or data is missing, return "not_configured" or an error.
2. Never claim guaranteed accuracy or profit, or that a trade will win or lose. Show backtests vs a naive baseline, uncertainty ranges and assumptions. Keep the disclaimer.
3. Deterministic code does the maths (ledger, tax, SIP/SWP, risk limits). An LLM only explains, classifies and drafts. No LLM access to the DB, filing or broker APIs; typed service functions only.
4. Respect licences: only providers whose terms allow the use. Users supply their own free keys in .env. No scraping.
5. No live trading, personalised stock advice or tax filing until legal review (SEBI RA/IA rules, broker approval, DPDP). Paper trading only.
6. UI theme: friendly luxury, warm ivory, champagne gold, emerald, blush; NOT blue, dark or violet. Keep the scrolling wallpaper, respect prefers-reduced-motion, WCAG AA contrast.

Phases (commit per phase, tests per phase)
P1 Migrate server.py to FastAPI + Pydantic schemas, keep core.py logic. Add pytest + httpx tests. Move to PostgreSQL via SQLAlchemy + Alembic (SQLite stays for local).
P2 Rebuild UI in React + Vite + Recharts with the same design tokens, using the BizMind-style layout (sidebar, KPI cards, forecast, demand and inventory, customer behaviour, AI assistant, automations, integrations, system status).
P3 Data: Excel upload, manual entry, HMAC-signed webhooks, Shopify/WooCommerce/Google Sheets connectors, inventory, customer, marketing and expense datasets, data-quality scoring.
P4 Models: statsmodels ETS/SARIMA, LightGBM with lag features, per-SKU demand; walk-forward backtests, interval calibration, model registry, frozen forecast ledger that scores outcomes later.
P5 Agents: tool registry, structured outputs, approval queue for automations (reports, low-stock alerts, follow-ups), email/WhatsApp notifications, audit trail.
P6 Billing: plans, quotas, Razorpay/Stripe webhooks, invoices; optional SSO.
P7 Finance: SIP/SWP/FD/RD/goal planners, LIC and insurance comparison from user-supplied illustrations, double-entry ledger, GST-ready invoices, bank CSV reconciliation, versioned tax rules reviewed by a CA.
P8 Markets: provider adapters with a canonical schema (source, as_of, delay, unit, licence), IPO calendar from an official or licensed source, cricket via a licensed API, freshness labels, paper trading with risk engine and kill switch.
P9 Assistant: local open-source LLM (Ollama) with RAG over the user's own data and cited official sources, prompt-injection defences, hallucination eval set. Fine-tune only after an evaluation set exists.
P10 Hardening: threat model, rate limits, MFA, encrypted backups, structured logging, CI (lint, tests, dependency scan), Docker Compose, staging/prod, runbooks, load tests, deploy to a VPS or Render/Fly behind HTTPS.

After each phase: update README, run all tests, and list what is verified vs unverified.
