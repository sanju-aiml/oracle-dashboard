# ORACLE: AI Business Prediction & Decision Intelligence SaaS Platform (v2.0)

A production-ready AI Business Prediction, Decision Intelligence, and Financial Workspace built for small shops, e-commerce sellers, startups, and growing enterprises (India-first, global-ready).

---

## 🌟 Key Architecture & Capabilities

### 1. Business Intelligence & Predictive Analytics
- **Multi-Model Forecasting Suite**: Holt-Winters Exponential Smoothing, Seasonal Naive, Trend-Seasonal, and Autoregressive Ridge Regression with walk-forward cross-validation.
- **Honest Backtesting vs Baseline**: Evaluates models against a naive baseline across out-of-sample folds. Computes MAE, RMSE, and skill score. If the model fails to beat the naive baseline, it transparently flags `No reliable edge`.
- **Uncertainty Calibration**: Dynamically shades an 80% confidence interval band based on historical out-of-sample error distributions.
- **Data Integrity**: Every data point strictly carries `kind: actual | calculated | estimate | forecast`.

### 2. Multi-Agent AI System (6 Autonomous Specialist Agents)
1. **Data Quality Agent**: Audits date intervals, missing values, duplicates, and non-numeric records; calculates a 0–100 Data Health Score.
2. **Demand & Inventory Agent**: Analyzes sales velocity and quarter-on-quarter acceleration; flags demand spikes and inventory bloat.
3. **Financial Forecasting Agent**: Ranks model candidates, calculates skill vs naive baseline, and explains predictive uncertainty.
4. **Cash Flow & Runway Agent**: Monitors operating profit margins, burn rate, and computes remaining cash runway in months.
5. **Anomaly & Risk Detection Agent**: Detects revenue and expense outliers using residual standard deviations (Z-score > 2.5).
6. **Customer & Growth Agent**: Tracks customer acquisition velocity, order volume trends, and ticket sizes.

### 3. Ingestion & Data Hub
- **Multi-Format Ingestion**: Supports CSV and Excel (`.xlsx`) spreadsheets with automatic column mapping (`sales`/`revenue`, `costs`/`expenses`).
- **Manual Data Entry**: Append single monthly records directly from the interface.
- **Synthetic Demo Data**: Pre-loaded 36-month realistic business dataset clearly marked with the `SYNTHETIC DEMO DATA` badge.

### 4. Demand & Inventory Planner (EOQ & Safety Stock)
- **SKU-Level Intelligence**: Calculates Economic Order Quantity (EOQ), Safety Stock, Reorder Point (ROP), and Days of Stock Remaining.
- **Stockout Risk Rating**: Automatically flags high-risk inventory items nearing reorder thresholds.

### 5. Financial Calculators & Decision Tools (Deterministic Math)
- **SIP & Step-up SIP**: Compound growth with optional annual percentage step-up.
- **SWP Retirement Planner**: Simulates corpus longevity and detects exact month of depletion.
- **LIC & Endowment Policy Evaluator**: Computes true Internal Rate of Return (IRR) from user's benefit illustration inputs and compares against index mutual funds (12% CAGR) with statutory disclaimers.
- **Fixed Deposit (FD) & Recurring Deposit (RD)**: Standard quarterly compounding returns.
- **GST Invoice Calculator**: Generates subtotal, CGST, SGST, IGST, and invoice totals.

### 6. Markets, IPOs & Cricket Intelligence
- **Live Spot Commodities**: Gold (XAU) and Silver (XAG) via Alpha Vantage.
- **Stock Outlook Engine**: 5-day predictive trajectory with baseline edge check.
- **Official IPO Tracker**: BSE/NSE IPO filings, status, issue size, and price bands.
- **International Cricket Predictor**: Duckworth-Lewis-Stern resource calculation, required run rate pressure index, and statistical win probability simulator.
- **Virtual Paper Trading Engine**: ₹10,00,000 sandbox capital, position sizing safeguards (max 35% in single asset), and an automatic 5% daily drawdown kill-switch.

### 7. Enterprise Security, Multi-Tenancy & Billing
- **FastAPI + Async Architecture**: Modern OpenAPI documentation at `/docs`, CORS middleware, Pydantic data schemas, and standard-library HTTP server compatibility.
- **Authentication & RBAC**: PBKDF2-HMAC-SHA256 password hashing (200,000 iterations), URL-safe signed session tokens, multi-workspace isolation, and roles (`owner`, `analyst`, `viewer`).
- **Audit Trail**: Logs all file uploads, logins, configuration adjustments, and automation approvals.
- **Billing & Subscriptions**: Starter (₹0), Pro (₹2,499/mo), and Enterprise (₹9,999/mo) plans with automated GST invoice generation.
- **Automations & Approvals**: Human-in-the-loop approval queue for purchase order drafts and anomaly reviews.

### 8. Luxury Theme & Responsive UX
- **Warm Ivory, Champagne Gold, Emerald Green & Blush Accents**: Strictly compliant with brand aesthetic; no blue, dark, or violet themes.
- **Ambient Scrolling Wallpaper**: Drifting diamond lattice with ambient glow (respects `prefers-reduced-motion`).
- **Live Marquee Ticker**: Real-time ticker tape displaying financial and commodity alerts.

---

## 🚀 Getting Started (₹0 Budget Local Run)

### 1. Prerequisites
- Python 3.10+ (or Python 3.14 via `uv`)

### 2. Setup Environment
```bash
# Clone the repository
git clone <repo-url>
cd oracle

# Create virtual environment and install dependencies
uv venv .venv
.\.venv\Scripts\activate
uv pip install -r requirements.txt --native-tls --link-mode=copy

# Configure environment variables
cp .env.example .env
```

### 3. Run the Server
```bash
# Start via Python (starts FastAPI with uvicorn or stdlib fallback)
.\.venv\Scripts\python server.py

# Or directly with Uvicorn
.\.venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8000 --reload
```
Open **[http://localhost:8000](http://localhost:8000)** in your browser. Interactive OpenAPI documentation is available at **[http://localhost:8000/docs](http://localhost:8000/docs)**.

---

## 🧪 Testing

Run both the unit test suite and the FastAPI integration test suite:

```bash
# Run existing deterministic core tests (10 tests)
.\.venv\Scripts\python -m unittest tests/test_core.py -v

# Run FastAPI, calculators, billing, cricket, and automation tests
.\.venv\Scripts\pytest tests/test_fastapi_and_features.py -v
```

All 14 test suites are automated and green.

---

## ⚖️ Regulatory & Compliance Disclaimers
1. **Forecasts are estimates, not guarantees**: Market and financial models compute statistical probabilities based on historical backtesting. Past performance is no guarantee of future results.
2. **SEBI/SEC Compliance**: This platform is designed for decision support and scenario modeling. It does not provide personalized investment advice or guaranteed trade execution.
3. **No Fabricated Data**: Provider APIs return real data if configured in `.env`. When unconfigured, the system explicitly reports `not_configured`.
4. **LIC Illustrations**: Endowment policy maturity calculations rely directly on numbers entered from the insurer's official benefit illustration. Bonuses are not guaranteed by any government authority.
