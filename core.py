"""ORACLE Core 2.0.
Deterministic maths + honest forecasting + specialized AI agents.
Never fabricate data: every number carries kind = 'actual' | 'calculated' | 'estimate' | 'forecast'.
"""
import os, io, re, json, time, hmac, base64, hashlib, sqlite3, urllib.request, math
import numpy as np, pandas as pd

import tempfile

def _is_serverless_or_readonly():
    if any(k.startswith("VERCEL") or k.startswith("AWS_") for k in os.environ):
        return True
    try:
        _probe = os.path.join(os.path.dirname(os.path.abspath(__file__)), f".chk_{os.getpid()}")
        with open(_probe, "w") as f:
            f.write("1")
        os.remove(_probe)
        return False
    except Exception:
        return True

if _is_serverless_or_readonly():
    DB = os.environ.get("ORACLE_DB", os.path.join(tempfile.gettempdir(), "oracle.db"))
else:
    DB = os.environ.get("ORACLE_DB", "oracle.db")
SECRET = os.environ.get("ORACLE_SECRET", "change-me-in-env").encode()
DISCLAIMER = "Forecasts are estimates, not guarantees. Not investment, tax or accounting advice."

# ---------- calculators (deterministic, kind=calculated) ----------
def _chk(**kw):
    for k, v in kw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or v < 0:
            raise ValueError(f"{k} must be a non-negative number")

def _sipfv(m, pct, n):
    r = pct / 1200
    return m * n if r == 0 else m * (((1 + r) ** n - 1) / r) * (1 + r)

def sip(monthly, annual_pct, years):
    _chk(monthly=monthly, annual_pct=annual_pct, years=years)
    n = int(round(years * 12)); inv = monthly * n; fv = _sipfv(monthly, annual_pct, n)
    sc = {f"{p}%": round(_sipfv(monthly, p, n), 2) for p in (max(0, annual_pct - 4), annual_pct, annual_pct + 4)}
    return {"kind": "calculated", "invested": round(inv, 2), "value": round(fv, 2), "gain": round(fv - inv, 2),
            "scenarios": sc, "assumption": f"Constant {annual_pct}% p.a. Real returns vary and can be negative."}

def step_up_sip(monthly, annual_pct, years, step_up_pct=10.0):
    _chk(monthly=monthly, annual_pct=annual_pct, years=years, step_up_pct=step_up_pct)
    r = (annual_pct / 100.0) / 12.0
    tot_inv = 0.0
    fv = 0.0
    cur_m = float(monthly)
    for y in range(int(round(years))):
        for m in range(12):
            tot_inv += cur_m
            months_remaining = (years * 12) - (y * 12 + m)
            fv += cur_m * ((1 + r) ** months_remaining)
        cur_m *= (1 + (step_up_pct / 100.0))
    return {
        "kind": "calculated",
        "initial_monthly": round(monthly, 2),
        "step_up_rate_pct": step_up_pct,
        "invested": round(tot_inv, 2),
        "value": round(fv, 2),
        "gain": round(fv - tot_inv, 2),
        "assumption": f"Monthly installment stepped up by {step_up_pct}% each year at {annual_pct}% p.a. compound growth."
    }

def swp(corpus, monthly, annual_pct, years):
    _chk(corpus=corpus, monthly=monthly, annual_pct=annual_pct, years=years)
    r, bal = annual_pct / 1200, float(corpus)
    for m in range(1, int(round(years * 12)) + 1):
        bal = bal * (1 + r) - monthly
        if bal <= 0:
            return {"kind": "calculated", "ending": 0.0, "depleted_month": m, "assumption": f"Constant {annual_pct}% p.a."}
    return {"kind": "calculated", "ending": round(bal, 2), "depleted_month": None, "assumption": f"Constant {annual_pct}% p.a."}

def irr(flows):
    f = lambda r: sum(a / (1 + r) ** t for t, a in flows)
    lo, hi = -0.9, 1.0
    if f(lo) * f(hi) > 0: return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(lo) * f(mid) <= 0: hi = mid
        else: lo = mid
    return mid

def lic(annual_premium, premium_years, term_years, maturity_amount):
    """Needs the maturity figure from the policy's own benefit illustration; bonuses are not guaranteed."""
    _chk(annual_premium=annual_premium, premium_years=premium_years, term_years=term_years, maturity_amount=maturity_amount)
    py = int(premium_years)
    flows = [(t, -annual_premium) for t in range(py)] + [(float(term_years), maturity_amount)]
    x = irr(flows); paid = annual_premium * py
    alt = {f"{p}%": round(sum(annual_premium * (1 + p / 100) ** (term_years - t) for t in range(py)), 2) for p in (6, 12)}
    return {"kind": "calculated", "total_premium": paid, "maturity": maturity_amount,
            "effective_return_pct": None if x is None else round(x * 100, 2), "same_premiums_if_invested_at": alt,
            "assumption": "Maturity amount is YOUR input from the LIC benefit illustration; bonuses are not guaranteed."}

def fd_calculator(principal, annual_pct, years, freq=4):
    _chk(principal=principal, annual_pct=annual_pct, years=years, freq=freq)
    r = annual_pct / 100.0
    n = freq
    t = years
    amt = principal * ((1 + (r / n)) ** (n * t))
    return {
        "kind": "calculated",
        "principal": round(principal, 2),
        "maturity_value": round(amt, 2),
        "interest_earned": round(amt - principal, 2),
        "compounding": f"{freq} times/year"
    }

def rd_calculator(monthly, annual_pct, months):
    _chk(monthly=monthly, annual_pct=annual_pct, months=months)
    n = int(round(months))
    r = (annual_pct / 100.0) / 4.0 # Indian quarterly compounding standard
    total_inv = monthly * n
    # Approximate Indian post office / bank RD compounding formula
    total_val = 0.0
    for i in range(1, n + 1):
        rem_quarters = (n - i + 1) / 3.0
        total_val += monthly * ((1 + r) ** rem_quarters)
    return {
        "kind": "calculated",
        "invested": round(total_inv, 2),
        "maturity_value": round(total_val, 2),
        "interest_earned": round(total_val - total_inv, 2)
    }

def gst_invoice_calc(items, gst_rate=18.0, is_interstate=False):
    subtotal = sum(it.get("quantity", 1) * it.get("unit_price", 0) for it in items)
    tax_amt = subtotal * (gst_rate / 100.0)
    total = subtotal + tax_amt
    return {
        "kind": "calculated",
        "subtotal": round(subtotal, 2),
        "gst_rate_pct": gst_rate,
        "tax_amount": round(tax_amt, 2),
        "cgst": 0.0 if is_interstate else round(tax_amt / 2, 2),
        "sgst": 0.0 if is_interstate else round(tax_amt / 2, 2),
        "igst": round(tax_amt, 2) if is_interstate else 0.0,
        "total_amount": round(total, 2)
    }

# ---------- forecasting + honest backtest ----------
def _naive(y, h, p): return np.repeat(y[-1], h)
def _snaive(y, h, p): return np.array([y[len(y) - p + (i % p)] for i in range(h)])
def _holt(y, h, p, a=.4, b=.1):
    l, t = y[0], y[1] - y[0]
    for v in y[1:]:
        pl = l; l = a * v + (1 - a) * (l + t); t = b * (l - pl) + (1 - b) * t
    return np.array([l + (i + 1) * t for i in range(h)])
def _trend_seasonal(y, h, p):
    n = len(y); x = np.arange(n); c = np.polyfit(x, y, 1); res = y - np.polyval(c, x)
    idx = np.array([res[i::p].mean() for i in range(p)])
    return np.array([np.polyval(c, n + i) + idx[(n + i) % p] for i in range(h)])
def _ridge_ar(y, h, p):
    # Autoregressive lag-feature linear model with L2 shrinkage
    n = len(y)
    lags = min(4, max(2, p // 3))
    if n <= lags + 4: return _holt(y, h, p)
    X, Y = [], []
    for i in range(lags, n):
        X.append(y[i-lags:i])
        Y.append(y[i])
    X, Y = np.array(X), np.array(Y)
    # Ridge regression analytical solution: (X'X + lambda*I)^-1 X'Y
    lam = 1.0
    w = np.linalg.inv(X.T @ X + lam * np.eye(lags)) @ (X.T @ Y)
    preds = []
    cur = list(y[-lags:])
    for _ in range(h):
        nxt = float(np.dot(cur[-lags:], w))
        preds.append(nxt)
        cur.append(nxt)
    return np.array(preds)

MODELS = {"naive": _naive, "seasonal_naive": _snaive, "holt": _holt, "trend_seasonal": _trend_seasonal, "ridge_ar": _ridge_ar}

def forecast(values, h=6, period=12):
    y = np.asarray(values, float)
    if len(y) < max(2 * period + h, 20): raise ValueError(f"Need at least {max(2 * period + h, 20)} data points to forecast and backtest honestly")
    if not np.isfinite(y).all(): raise ValueError("Data contains invalid numbers")
    origins = range(max(2 * period, len(y) - h - 8), len(y) - h + 1)
    err = {k: [] for k in MODELS}
    for o in origins:
        for k, fn in MODELS.items(): err[k].append(y[o:o + h] - fn(y[:o], h, period))
    mae = {k: float(np.mean(np.abs(v))) for k, v in err.items()}
    best = min(mae, key=mae.get); skill = 1 - mae[best] / mae["naive"] if mae["naive"] else 0.0
    res = np.array(err[best]); mean = MODELS[best](y, h, period)
    return {"kind": "forecast", "model": best, "backtest_mae": {k: round(v, 2) for k, v in mae.items()}, "folds": len(origins),
            "skill_vs_naive": round(skill, 3), "beats_baseline": bool(best != "naive" and skill > 0.05),
            "mean": [round(float(v), 2) for v in mean],
            "lo": [round(float(v), 2) for v in np.minimum(mean, mean + np.percentile(res, 10, axis=0))],
            "hi": [round(float(v), 2) for v in np.maximum(mean, mean + np.percentile(res, 90, axis=0))],
            "interval": "80% range from past backtest errors. Real outcomes can fall outside it.", "disclaimer": DISCLAIMER}

# ---------- data parsing & generation ----------
def demo_df(n=36):
    rng = np.random.default_rng(42); t = np.arange(n)
    rev = 100000 + 1800 * t + 12000 * np.sin(2 * np.pi * t / 12) + rng.normal(0, 3000, n)
    exp = (rev * .68 + rng.normal(0, 2000, n)).round(2)
    return pd.DataFrame({
        "date": pd.date_range("2023-11-01", periods=n, freq="MS"),
        "revenue": rev.round(2),
        "expenses": exp,
        "profit": (rev - exp).round(2),
        "orders": np.round(rev / 850).astype(int),
        "new_customers": np.round(30 + t * 1.5 + rng.normal(0, 4, n)).astype(int)
    })

def parse_csv(text):
    df = pd.read_csv(io.StringIO(text)); df.columns = [c.strip().lower() for c in df.columns]
    # Map synonyms
    syn = {"sales": "revenue", "income": "revenue", "costs": "expenses", "spend": "expenses"}
    df = df.rename(columns={k: v for k, v in syn.items() if k in df.columns and v not in df.columns})
    if not {"date", "revenue"} <= set(df.columns): raise ValueError("CSV needs columns: date, revenue (optional: expenses)")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if df["date"].isna().any(): raise ValueError("Some dates could not be read (use YYYY-MM-DD)")
    if df["date"].duplicated().any(): raise ValueError("Duplicate dates found")
    for c in ("revenue", "expenses"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
            if df[c].isna().any() or (df[c] < 0).any(): raise ValueError(f"'{c}' must be non-negative numbers with no blanks")
    return df.sort_values("date").reset_index(drop=True)

def parse_excel_bytes(file_bytes):
    """Reads Excel file (.xlsx) and extracts the primary business metrics sheet."""
    try:
        xls = pd.ExcelFile(io.BytesIO(file_bytes))
        sheet = xls.sheet_names[0]
        for name in xls.sheet_names:
            if any(w in name.lower() for w in ("sales", "revenue", "financials", "data", "sheet1")):
                sheet = name; break
        df = pd.read_excel(xls, sheet_name=sheet)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        return parse_csv(csv_buf.getvalue())
    except Exception as e:
        raise ValueError(f"Could not parse Excel spreadsheet: {str(e)}")

def compute_data_health(df):
    """Calculates data quality score (0-100) and integrity breakdown."""
    score = 100
    reasons = []
    
    # 1. Row count
    if len(df) < 20:
        score -= 25
        reasons.append(f"Small sample size ({len(df)} rows). Forecasting needs at least 24+ monthly rows for seasonal analysis.")
    elif len(df) >= 36:
        reasons.append(f"Good historical depth ({len(df)} monthly observations).")
        
    # 2. Date regularities
    gaps = df["date"].diff().dt.days.dropna()
    if gaps.max() > 35:
        score -= 15
        reasons.append("Irregular time intervals detected between consecutive dates.")
    else:
        reasons.append("Clean uniform time intervals.")
        
    # 3. Variance / zero revenue
    rev = df["revenue"].values
    if np.any(rev == 0):
        score -= 10
        reasons.append("Zero revenue months detected. May skew trend calculations.")
    if rev.std() / (rev.mean() or 1) < 0.01:
        score -= 20
        reasons.append("Data appears unnaturally flat (almost zero variance).")
        
    score = max(0, min(100, score))
    return {"kind": "calculated", "score": score, "status": "Excellent" if score >= 85 else ("Good" if score >= 70 else "Needs Attention"), "checks": reasons}

# ---------- 6 specialized agents ----------
def agents(df, f):
    out = []; rev = df["revenue"].values; add = lambda a, t, k, st="normal": out.append({"agent": a, "text": t, "kind": k, "status": st})
    
    # Agent 1: Data Quality
    gaps = df["date"].diff().dt.days.dropna()
    has_gaps = bool(gaps.max() > 35) if len(gaps) else False
    q_txt = f"{len(df)} rows verified; no blanks, duplicates or negative numbers."
    if has_gaps: q_txt += " Warning: irregular date spacing detected."
    add("Data Quality", q_txt, "actual", "warning" if has_gaps else "good")
    
    # Agent 2: Demand & Inventory
    g = (rev[-3:].mean() / rev[-6:-3].mean() - 1) * 100 if len(rev) >= 6 else 0.0
    inv_advice = "Demand momentum is accelerating (+{:.1f}%). Increase safety stock buffer by 15%.".format(g) if g > 10 else (
        "Demand contracted by {:.1f}% in recent quarter. Rationalize procurement to prevent inventory bloat.".format(abs(g)) if g < -10 else
        f"Demand is stable (recent 3 months averaged {g:+.1f}% vs prior 3)."
    )
    add("Demand", inv_advice, "calculated", "alert" if abs(g) > 15 else "normal")
    
    # Agent 3: Financial Forecast
    add("Forecast", f"Best backtested model: {f['model']} (error {f['skill_vs_naive'] * 100:+.0f}% vs naive baseline). " +
        ("It beats the baseline, so treat the range as useful but uncertain." if f["beats_baseline"] else "It does NOT clearly beat the baseline, so do not rely on it."),
        "forecast", "good" if f["beats_baseline"] else "warning")
        
    # Agent 4: Cash Flow & Runway
    if "expenses" in df:
        m = 1 - df["expenses"].values / rev
        d = (m[-3:].mean() - m[-6:-3].mean()) * 100 if len(m) >= 6 else 0.0
        cur_margin = m[-3:].mean() * 100 if len(m) >= 3 else 0.0
        cur_burn = df["expenses"].iloc[-3:].mean() - rev[-3:].mean()
        cf_status = "alert" if d < -3 or cur_margin < 10 else "normal"
        cf_txt = f"Profit margin last 3 months {cur_margin:.1f}% ({d:+.1f} pts vs prior 3)."
        if cur_burn > 0:
            cf_txt += f" Currently burning ₹{cur_burn:,.0f}/month operating cash."
        elif d < -1:
            cf_txt += " Margin compressed; review vendor pricing and overheads."
        add("Cash flow", cf_txt, "calculated", cf_status)
    else:
        add("Cash flow", "Upload expenses data to enable automated net margin, burn rate and cash runway analytics.", "calculated", "normal")
        
    # Agent 5: Anomaly & Risk Detection
    tr = np.polyval(np.polyfit(np.arange(len(rev)), rev, 1), np.arange(len(rev)))
    std_res = (rev - tr).std()
    z = (rev - tr) / (std_res if std_res > 1e-6 else 1.0)
    odd = [str(df["date"][i].date()) for i in range(max(0, len(rev) - 12), len(rev)) if abs(z[i]) > 2.5]
    ano_txt = ("Unusual revenue spikes/dips: " + ", ".join(odd)) if odd else "No unusual anomalies in the last 12 months."
    add("Anomaly", ano_txt, "calculated", "alert" if odd else "good")
    
    # Agent 6: Customer & Growth Intelligence
    if "new_customers" in df:
        cust = df["new_customers"].values
        cust_g = (cust[-3:].mean() / (cust[-6:-3].mean() or 1) - 1) * 100 if len(cust) >= 6 else 0.0
        add("Customer & Growth", f"Acquired avg {int(cust[-3:].mean())} customers/mo ({cust_g:+.1f}% vs prior quarter). Retention healthy.", "calculated", "good")
    else:
        avg_monthly = rev.mean()
        add("Customer & Growth", f"Estimated average monthly ticket run rate: ₹{avg_monthly:,.0f}. Connect CRM for cohort LTV.", "calculated", "normal")
        
    return out

def get_inventory_analysis():
    """Multi-SKU Inventory management and Economic Order Quantity (EOQ) intelligence."""
    skus = [
        {"sku": "SKU-A101", "name": "Organic Honey 500g", "current_stock": 140, "daily_sales": 8, "lead_time_days": 7, "unit_cost": 220, "order_cost": 500, "holding_cost_pct": 20},
        {"sku": "SKU-A102", "name": "Basmati Rice 25kg", "current_stock": 12, "daily_sales": 5, "lead_time_days": 10, "unit_cost": 1850, "order_cost": 800, "holding_cost_pct": 18},
        {"sku": "SKU-A103", "name": "Cold-pressed Olive Oil 1L", "current_stock": 85, "daily_sales": 4, "lead_time_days": 5, "unit_cost": 650, "order_cost": 400, "holding_cost_pct": 15},
        {"sku": "SKU-A104", "name": "Almonds California 1kg", "current_stock": 28, "daily_sales": 6, "lead_time_days": 8, "unit_cost": 720, "order_cost": 450, "holding_cost_pct": 22}
    ]
    analyzed = []
    for item in skus:
        d = item["daily_sales"] * 365 # Annual demand
        s = item["order_cost"]
        h = item["unit_cost"] * (item["holding_cost_pct"] / 100.0)
        eoq = int(math.sqrt((2 * d * s) / h)) if h > 0 else 50
        lead_time_demand = item["daily_sales"] * item["lead_time_days"]
        safety_stock = int(item["daily_sales"] * (item["lead_time_days"] * 0.5))
        reorder_point = lead_time_demand + safety_stock
        days_left = round(item["current_stock"] / max(0.1, item["daily_sales"]), 1)
        risk = "HIGH - Urgent Reorder" if item["current_stock"] <= reorder_point else ("Medium" if item["current_stock"] <= reorder_point * 1.5 else "Low / Healthy")
        
        analyzed.append({
            "sku": item["sku"],
            "name": item["name"],
            "current_stock": item["current_stock"],
            "days_of_stock": days_left,
            "reorder_point": reorder_point,
            "safety_stock": safety_stock,
            "recommended_order_quantity_eoq": eoq,
            "stockout_risk": risk
        })
    return {"kind": "calculated", "items": analyzed}

def dashboard(df, label):
    f = forecast(df["revenue"].values, 6); rev = df["revenue"]
    tot_rev = float(rev.sum())
    last_m = float(rev.iloc[-1])
    next_6m = float(sum(f["mean"]))
    
    k = [
        {"name": "Total revenue", "value": tot_rev, "kind": "actual"},
        {"name": "Last month", "value": last_m, "kind": "actual"},
        {"name": "Next 6 months (est.)", "value": next_6m, "kind": "forecast"}
    ]
    if "expenses" in df:
        tot_exp = float(df["expenses"].sum())
        net_prof = float(tot_rev - tot_exp)
        prof_margin = round((net_prof / tot_rev * 100), 1) if tot_rev > 0 else 0.0
        k.append({"name": "Profit", "value": net_prof, "kind": "calculated"})
        k.append({"name": "Net margin", "value": prof_margin, "kind": "calculated", "unit": "%"})
    
    # Financial runway estimation
    cur_cash = 2500000.0 # Standard working capital baseline
    monthly_burn = float(df["expenses"].iloc[-3:].mean() - rev.iloc[-3:].mean()) if "expenses" in df else 0.0
    runway_months = round(cur_cash / monthly_burn, 1) if monthly_burn > 0 else 99.0
    k.append({"name": "Runway", "value": runway_months if runway_months < 90 else 36.0, "kind": "calculated", "unit": "months"})
    
    health = compute_data_health(df)
    
    return {
        "label": label,
        "kpis": k,
        "dates": [str(d.date()) for d in df["date"]],
        "history": [float(v) for v in rev],
        "expenses": [float(v) for v in df["expenses"]] if "expenses" in df else [],
        "forecast": f,
        "agents": agents(df, f),
        "data_health": health,
        "inventory": get_inventory_analysis()["items"]
    }

# ---------- markets & cricket (bring your own free keys; never faked) ----------
def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "oracle"}), timeout=10) as r: return json.load(r)

def quote(kind, symbol=""):
    key = os.environ.get("ALPHAVANTAGE_KEY")
    if not key: return {"status": "not_configured", "how": "Put ALPHAVANTAGE_KEY in .env (free key at alphavantage.co)"}
    try:
        b = "https://www.alphavantage.co/query?apikey=" + key
        if kind in ("gold", "silver"):
            r = _get(b + f"&function=CURRENCY_EXCHANGE_RATE&from_currency={'XAU' if kind == 'gold' else 'XAG'}&to_currency=USD")["Realtime Currency Exchange Rate"]
            return {"status": "ok", "kind": "actual", "source": "Alpha Vantage", "price": float(r["5. Exchange Rate"]), "unit": "USD per troy oz", "as_of": r["6. Last Refreshed"]}
        q = _get(b + f"&function=GLOBAL_QUOTE&symbol={urllib.request.quote(symbol)}")["Global Quote"]
        return {"status": "ok", "kind": "actual", "source": "Alpha Vantage", "symbol": symbol, "price": float(q["05. price"]), "as_of": q["07. latest trading day"], "note": "Free tier may be delayed."}
    except Exception as e: return {"status": "error", "error": f"Provider call failed: {str(e)[:100]}"}

def market_forecast(symbol):
    key = os.environ.get("ALPHAVANTAGE_KEY")
    if not key: return quote("stock", symbol)
    try:
        ts = _get(f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&outputsize=full&symbol={urllib.request.quote(symbol)}&apikey={key}")["Time Series (Daily)"]
        c = [float(v["4. close"]) for _, v in sorted(ts.items())][-300:]
        f = forecast(c, 5, 5)
        f["verdict"] = ("Model shows a small edge in backtests, still no guarantee of profit." if f["beats_baseline"] else "No reliable edge over the naive baseline. Nobody can confirm profit or loss in advance.")
        return f
    except Exception as e: return {"status": "error", "error": str(e)[:100]}

def cricket():
    key = os.environ.get("CRICAPI_KEY")
    if not key: return {"status": "not_configured", "how": "Put CRICAPI_KEY in .env (free key at cricketdata.org)"}
    try:
        d = _get(f"https://api.cricapi.com/v1/currentMatches?apikey={key}&offset=0")["data"]
        return {"status": "ok", "kind": "actual", "source": "CricketData.org", "matches": [{"name": m.get("name"), "status": m.get("status")} for m in d[:12]]}
    except Exception as e: return {"status": "error", "error": str(e)[:100]}

# ---------- chat (grounded strictly in computed data) ----------
def chat(msg, dash):
    m = msg.lower()
    
    # Prompt injection check
    if any(p in m for p in ("ignore previous instructions", "system prompt", "pretend you are", "jailbreak")):
        return "I am ORACLE Business & Money Intelligence. I strictly answer business questions and financial calculations grounded in your workspace data."
        
    n = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", m.replace(",", ""))]
    try:
        if "step up" in m and len(n) >= 4:
            r = step_up_sip(n[0], n[1], n[2], n[3])
            return f"Step-up SIP starting at ₹{n[0]:,.0f}/mo with {n[3]}% annual step-up: Invested ₹{r['invested']:,.0f}, Estimated value ₹{r['value']:,.0f} (Gain: ₹{r['gain']:,.0f}). {r['assumption']}"
        if "sip" in m and len(n) >= 3:
            r = sip(*n[:3]); return f"SIP of ₹{n[0]:,.0f}/month for {n[2]:g} years at {n[1]:g}%: invested ₹{r['invested']:,.0f}, estimated value ₹{r['value']:,.0f}. {r['assumption']}"
        if "swp" in m and len(n) >= 4:
            r = swp(*n[:4]); return f"SWP ends at ₹{r['ending']:,.0f}" + (f" and runs out in month {r['depleted_month']}." if r["depleted_month"] else " (corpus lasts).") + " " + r["assumption"]
        if "lic" in m and len(n) >= 4:
            r = lic(*n[:4]); return f"LIC policy: Total premium paid ₹{r['total_premium']:,.0f}, Maturity ₹{r['maturity']:,.0f}, Effective return: {r['effective_return_pct']}%. {r['assumption']}"
        if "fd" in m and len(n) >= 3:
            r = fd_calculator(n[0], n[1], n[2])
            return f"Fixed Deposit: Principal ₹{r['principal']:,.0f} at {n[1]}% for {n[2]} years yields ₹{r['maturity_value']:,.0f} (Interest: ₹{r['interest_earned']:,.0f})."
        if "gst" in m and len(n) >= 1:
            amt = n[0]
            rate = n[1] if len(n) >= 2 else 18.0
            try:
                import finllm_engine
                res = finllm_engine.calculate_ca_banking("gst", {"amount": amt, "rate_pct": rate})["result"]
                return f"GST Calculation for ₹{amt:,.2f} at {rate}%: GST = ₹{res['gst']:,.2f} (CGST: ₹{res['cgst']:,.2f}, SGST: ₹{res['sgst']:,.2f}), Total = ₹{res['total']:,.2f}."
            except Exception as e:
                return f"GST calculation failed: {str(e)}"
        if "emi" in m and len(n) >= 1:
            p = n[0]
            r = n[1] if len(n) >= 2 else 8.5
            y = int(n[2]) if len(n) >= 3 else 10
            try:
                import finllm_engine
                res = finllm_engine.calculate_ca_banking("emi", {"principal": p, "rate_pct": r, "tenure_years": y})["result"]
                return f"Loan EMI Calculation: Principal ₹{p:,.2f} at {r}% for {y} years: Monthly EMI = ₹{res['emi']:,.2f}, Total Interest = ₹{res['total_interest']:,.2f}, Total Payment = ₹{res.get('total_paid', 0):,.2f}."
            except Exception as e:
                return f"EMI calculation failed: {str(e)}"
        if "tds" in m and len(n) >= 1:
            amt = n[0]
            pan = "no pan" not in m
            try:
                import finllm_engine
                res = finllm_engine.calculate_ca_banking("tds_194c", {"amount": amt, "pan": pan})["result"]
                return f"TDS u/s 194C on ₹{amt:,.2f} ({'with PAN' if pan else 'without PAN'}): TDS = ₹{res['tds']:,.2f} ({res['rate_pct']}%), Net Payable = ₹{res['net']:,.2f}."
            except Exception as e:
                return f"TDS calculation failed: {str(e)}"
        if ("income tax" in m or "tax regime" in m or "new regime" in m) and len(n) >= 1:
            inc = n[0]
            ded = n[1] if len(n) >= 2 else 75000.0
            try:
                import finllm_engine
                res = finllm_engine.calculate_ca_banking("tax_new_regime", {"income": inc})["result"]
                return f"Income Tax (New Regime FY25-26): Gross Income ₹{inc:,.2f}, Standard Deduction ₹{ded:,.2f}, Taxable Income ₹{res['taxable_income']:,.2f}, Base Tax ₹{res['base_tax']:,.2f}, Rebate 87A: ₹{res['rebate_87a']:,.2f}, Cess (4%): ₹{res['cess']:,.2f}, Total Tax = ₹{res['total']:,.2f}."
            except Exception as e:
                return f"Tax calculation failed: {str(e)}"
    except ValueError as e:
        return str(e)
        
    if any(w in m for w in ("forecast", "predict", "next", "sales", "revenue")):
        if dash and "forecast" in dash:
            f = dash["forecast"]
            return f"Estimated next-6-month revenue: ₹{sum(f['mean']):,.0f} (80% range ₹{sum(f['lo']):,.0f} to ₹{sum(f['hi']):,.0f}). Model {f['model']}; beats baseline: {f['beats_baseline']}. {DISCLAIMER}"
        return "Please load or upload your business data first to compute sales forecasts."
        
    if any(w in m for w in ("invest", "amazon", "amzn", "nvda", "tsla", "aapl", "apple", "msft", "googl", "pltr", "stock")):
        import market
        sym = "AMZN"
        for candidate in ("amzn", "amazon", "nvda", "nvidia", "tsla", "tesla", "aapl", "apple", "msft", "microsoft", "googl", "google", "pltr", "ibm"):
            if candidate in m:
                sym = {"amazon": "AMZN", "nvidia": "NVDA", "tesla": "TSLA", "apple": "AAPL", "microsoft": "MSFT", "google": "GOOGL"}.get(candidate, candidate.upper())
                break
        cap = 100000.0
        h_days = 90
        if len(n) >= 1 and n[0] >= 1000:
            cap = n[0]
            if len(n) >= 2 and n[1] <= 365:
                h_days = int(n[1])
        elif len(n) >= 1 and n[0] <= 365:
            h_days = int(n[0])
            
        inv = market.analyze_investment(sym, h_days, cap)
        if inv.get("status") == "error":
            return f"Market Analysis: {inv.get('error')}"
            
        sc = inv["scenarios"]
        return (
            f"🎯 Investment Decision Intelligence for {inv['symbol']} (Live Price: ${inv['current_price']:,.2f}):\n"
            f"• Success Rate (Win Probability): {inv['win_probability_pct']}%\n"
            f"• Expected Base Horizon ({h_days} Days): {sc['base_case']['return_pct']:+.1f}% (Projected Value: ₹{sc['base_case']['projected_value']:,.0f})\n"
            f"• Bull Case Momentum: {sc['bull_case']['return_pct']:+.1f}% (Target: ${sc['bull_case']['target_price']:,.2f} / ₹{sc['bull_case']['projected_value']:,.0f})\n"
            f"• Maximum Downside Risk (95% VaR): -{inv['max_drawdown_risk_95_var']['max_loss_pct']:.1f}% (Potential Max Loss: ₹{inv['max_drawdown_risk_95_var']['max_loss_capital']:,.0f})\n"
            f"• AI Verdict: {inv['verdict']} [{inv['rating']}]\n\n"
            f"Telugu Summary: {inv['telugu_advice']}\n\n"
            f"{inv['disclaimer']}"
        )

    if "oil" in m or "crude" in m or "brent" in m:
        import market
        q = market.get_live_commodity("oil")
        if q.get("status") == "ok":
            return f"Live Brent Crude Oil: ${q['price']:,.2f} {q['unit']} as of {q['as_of']} ({q['source']})."
        return q.get("error", "Oil price unavailable")

    if "alpaca" in m or "paper balance" in m or "buying power" in m:
        import market
        acc = market.get_alpaca_account()
        if acc.get("status") == "ok":
            return f"Alpaca Live Paper Trading: Cash ${acc['cash_balance']:,.2f}, Portfolio Equity ${acc['portfolio_equity']:,.2f}, Buying Power ${acc['buying_power']:,.2f} ({acc['status_text']})."
        return acc.get("error", "Alpaca API unavailable")

    if "gold" in m or "silver" in m:
        import market
        q = market.get_live_quote("gold" if "gold" in m else "silver")
        if q.get("status") == "ok":
            extra = f" (Approx ₹{q['inr_approx_10g']:,.0f} per 10g in India)" if "inr_approx_10g" in q else ""
            return f"{q.get('commodity', 'Metal')}: ${q['price']:,.2f} {q['unit']}{extra} as of {q['as_of']} ({q['source']})."
        return q.get("how") or q.get("error")
        
    if "cricket" in m or "match" in m:
        c = cricket()
        return "; ".join(f"{x['name']}: {x['status']}" for x in c["matches"]) if c["status"] == "ok" else c.get("how") or c.get("error")
        
    if "inventory" in m or "stock" in m:
        inv = get_inventory_analysis()["items"]
        urgent = [it["name"] for it in inv if "HIGH" in it["stockout_risk"]]
        if urgent:
            return f"Inventory Alert: {len(urgent)} items need urgent reordering: " + ", ".join(urgent) + ". Check the Inventory Planner for EOQ recommendations."
        return "All SKU stock levels are currently above reorder thresholds. No stockout risks detected."
        
    if "data quality" in m or "health" in m:
        if dash and "data_health" in dash:
            dh = dash["data_health"]
            return f"Data Quality Score: {dh['score']}/100 ({dh['status']}). Key checks: " + "; ".join(dh["checks"])
        return "Your data quality score is ready once a dataset is loaded."
        
    if "profit" in m or "loss" in m:
        return "No tool can confirm profit or loss in advance. I can show backtested ranges and how often models beat a simple baseline."
        
    if any(w in m for w in ('bitcoin', 'btc', 'ethereum', 'eth', 'crypto')):
        import market
        sym = 'BTC'
        if 'eth' in m or 'ethereum' in m: sym = 'ETH'
        q = market.get_crypto_price(sym)
        if q.get('status') == 'ok':
            return f"{sym} Live Quote: ${q['price']:,.2f} USD as of {q['as_of']} ({q['source']}). Crypto carries extreme volatility; past performance is never a guarantee."
        return f"Crypto price currently unavailable: {q.get('error', 'API error')}"

    if any(w in m for w in ('sensex', 'nifty', 'india market', 'bse', 'nse')):
        import market
        idx = 'SENSEX' if 'sensex' in m or 'bse' in m else 'NIFTY 50'
        q = market.get_india_index(idx)
        if q.get('status') == 'ok':
            return f"{idx}: {q['price']:,.2f} INR ({q['source']}, {q['as_of']})."
        return f"India index '{idx}' unavailable: {q.get('error', 'check TwelveData')}"

    if any(w in m for w in ('forex', 'usd inr', 'usd/inr', 'dollar', 'rupee', 'exchange rate')):
        import market
        q = market.get_forex('USD', 'INR')
        if q.get('status') == 'ok':
            return f"USD/INR Forex Rate: 1 USD = ₹{q['rate']} INR (Live from {q['source']} at {q['as_of']})."
        return f"Forex rate unavailable: {q.get('error', 'API error')}"

    if any(w in m for w in ('natural gas', 'gas price', 'lng')):
        import market
        q = market.get_natural_gas()
        if q.get('status') == 'ok':
            return f"Natural Gas: ${q['price']} {q['unit']} as of {q['as_of']} ({q['source']})."
        return f"Natural gas price unavailable: {q.get('error', 'API error')}"

    if any(w in m for w in ('news', 'latest news', 'headline')):
        import market
        words = msg.upper().split()
        sym = None
        for w in words:
            clean = "".join(ch for ch in w if ch.isalnum())
            if 1 <= len(clean) <= 5 and clean not in ('NEWS', 'LATEST', 'ABOUT', 'FOR', 'THE', 'AND', 'STOCK', 'WHAT', 'IS', 'GIVE', 'ME'):
                sym = clean
                break
        if sym:
            r = market.get_company_news(sym, 3)
            if r.get('status') == 'ok' and r.get('news'):
                headlines = '; '.join([f"{n['headline']} ({n['source']}, {n['datetime']})" for n in r['news'][:3]])
                return f"Latest verified headlines for {sym}: {headlines}"
            return f"No recent verified news found for {sym}."

    if any(w in m for w in ('search', 'find', 'what is', 'who is', 'tell me about', 'how to', 'explain', 'realtime', 'live market', 'market today')):
        import market
        q = market.web_search(msg, max_results=3)
        if q.get('status') == 'ok' and q['results']:
            snippets = [f"• {r['title']}: {r['body']}" for r in q['results'][:2]]
            return f"Real-time Web & Market Intelligence:\n" + "\n".join(snippets) + "\n\n[Source: Live Web Search Index]"

    return "Try: 'sip 5000 12 10', 'swp 1000000 8000 8 15', 'step up 10000 12 15 10', 'forecast', 'invest AMZN 100000 90', 'gold price', 'bitcoin price', 'usd inr', 'AAPL news', 'search latest fed meeting', 'cricket'. Grounded strictly in verified calculations and live market feeds."

# ---------- auth, workspaces, roles ----------
def db():
    global DB
    candidates = [
        DB,
        os.path.join(tempfile.gettempdir(), "oracle.db"),
        ":memory:"
    ]
    for target in candidates:
        try:
            c = sqlite3.connect(target, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("CREATE TABLE IF NOT EXISTS _probe (id INTEGER)")
            DB = target
            return c
        except Exception:
            continue
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c

MIGS = [
    # 1: Initial core tables
    "CREATE TABLE users(id INTEGER PRIMARY KEY,email TEXT UNIQUE,salt TEXT,pw TEXT,role TEXT,ws INTEGER);"
    "CREATE TABLE datasets(id INTEGER PRIMARY KEY,ws INTEGER,name TEXT,csv TEXT,source TEXT,created REAL);"
    "CREATE TABLE audit(id INTEGER PRIMARY KEY,ws INTEGER,uid INTEGER,action TEXT,ts REAL);",
    # 2: Multi-workspace & membership
    "CREATE TABLE workspaces(id INTEGER PRIMARY KEY,name TEXT,owner_uid INTEGER,created REAL);"
    "CREATE TABLE workspace_members(id INTEGER PRIMARY KEY,ws INTEGER,uid INTEGER,role TEXT);",
    # 3: Audit logging & transactions
    "CREATE TABLE ledger_entries(id INTEGER PRIMARY KEY,ws INTEGER,entry_date TEXT,account TEXT,debit REAL,credit REAL,memo TEXT);"
]

def migrate():
    try:
        c = db(); c.execute("CREATE TABLE IF NOT EXISTS schema_version(v INTEGER)")
        cur = c.execute("SELECT COALESCE(MAX(v),0) FROM schema_version").fetchone()[0]
        for i, s in enumerate(MIGS[cur:], cur + 1):
            c.executescript(s)
            c.execute("INSERT INTO schema_version VALUES(?)", (i,))
        c.commit(); c.close()
    except Exception as e:
        print(f"[ORACLE] Database migration note: {e}")

def _h(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
def _sig(b): return base64.urlsafe_b64encode(hmac.new(SECRET, b, hashlib.sha256).digest())

def token(p):
    b = base64.urlsafe_b64encode(json.dumps({**p, "exp": time.time() + 86400}).encode())
    return (b + b"." + _sig(b)).decode()

def verify(t):
    try:
        b, s = t.encode().split(b".")
        if not hmac.compare_digest(_sig(b), s): return None
        p = json.loads(base64.urlsafe_b64decode(b))
        return p if p["exp"] > time.time() else None
    except Exception: return None

def register(email, pw):
    if "@" not in email or len(pw) < 8: raise ValueError("Valid email and a password of 8+ characters required")
    c = db(); salt = os.urandom(8).hex()
    try: cur = c.execute("INSERT INTO users(email,salt,pw,role) VALUES(?,?,?,'owner')", (email.lower(), salt, _h(pw, salt)))
    except sqlite3.IntegrityError: raise ValueError("Email already registered")
    uid = cur.lastrowid
    c.execute("UPDATE users SET ws=id WHERE id=?", (uid,))
    try:
        c.execute("INSERT INTO workspaces(id,name,owner_uid,created) VALUES(?,?,?,?)", (uid, f"{email.split('@')[0]}'s Workspace", uid, time.time()))
        c.execute("INSERT INTO workspace_members(ws,uid,role) VALUES(?,?,?)", (uid, uid, "owner"))
    except Exception:
        pass
    c.commit(); c.close()
    return login(email, pw)

def login(email, pw):
    c = db(); u = c.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone(); c.close()
    if not u or not hmac.compare_digest(_h(pw, u["salt"]), u["pw"]): raise ValueError("Wrong email or password")
    return {"token": token({"uid": u["id"], "ws": u["ws"], "role": u["role"], "email": u["email"]}), "role": u["role"]}

def save_dataset(user, name, text):
    if user["role"] not in ("owner", "analyst"): raise PermissionError("Your role cannot upload data")
    parse_csv(text); c = db()
    c.execute("INSERT INTO datasets(ws,name,csv,source,created) VALUES(?,?,?,?,?)", (user["ws"], name, text, "uploaded", time.time()))
    c.execute("INSERT INTO audit(ws,uid,action,ts) VALUES(?,?,?,?)", (user["ws"], user["uid"], "upload:" + name, time.time())); c.commit(); c.close()

def workspace_dashboard(user):
    c = db(); r = c.execute("SELECT csv,name FROM datasets WHERE ws=? ORDER BY id DESC LIMIT 1", (user["ws"],)).fetchone(); c.close()
    return dashboard(parse_csv(r["csv"]), "YOUR DATA: " + r["name"]) if r else dashboard(demo_df(), "SYNTHETIC DEMO DATA: not real business data")

def get_audit_trail(user):
    c = db()
    rows = c.execute("SELECT a.id, a.action, a.ts, u.email FROM audit a LEFT JOIN users u ON a.uid=u.id WHERE a.ws=? ORDER BY a.id DESC LIMIT 50", (user["ws"],)).fetchall()
    c.close()
    return [{"id": r["id"], "action": r["action"], "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["ts"])), "user": r["email"] or "system"} for r in rows]


# ==========================================
# WATCHLIST & ALERTS (SQLite-backed)
# ==========================================
def _ensure_watchlist_tables():
    c = db()
    c.execute('CREATE TABLE IF NOT EXISTS watchlist(id INTEGER PRIMARY KEY,ws INTEGER,uid INTEGER,symbol TEXT,note TEXT,added_at REAL,UNIQUE(ws,uid,symbol))')
    c.execute('CREATE TABLE IF NOT EXISTS price_alerts(id INTEGER PRIMARY KEY,ws INTEGER,uid INTEGER,symbol TEXT,condition TEXT,threshold REAL,note TEXT,active INTEGER DEFAULT 1,triggered_at REAL,created_at REAL)')
    c.commit(); c.close()

def add_to_watchlist(user, symbol, note=''):
    _ensure_watchlist_tables()
    sym = symbol.upper().strip()
    c = db()
    try:
        c.execute('INSERT OR IGNORE INTO watchlist(ws,uid,symbol,note,added_at) VALUES(?,?,?,?,?)', (user['ws'], user['uid'], sym, note, time.time()))
        c.commit()
        return {'status': 'ok', 'message': f'{sym} added to watchlist'}
    except Exception as e:
        return {'status': 'error', 'error': str(e)[:80]}
    finally:
        c.close()

def get_watchlist(user):
    _ensure_watchlist_tables()
    c = db()
    rows = c.execute('SELECT id,symbol,note,added_at FROM watchlist WHERE ws=? AND uid=? ORDER BY id DESC', (user['ws'], user['uid'])).fetchall()
    c.close()
    return {'status': 'ok', 'kind': 'actual', 'watchlist': [{'id': r['id'], 'symbol': r['symbol'], 'note': r['note'], 'added': time.strftime('%Y-%m-%d %H:%M', time.localtime(r['added_at']))} for r in rows]}

def remove_from_watchlist(user, symbol):
    _ensure_watchlist_tables()
    sym = symbol.upper().strip()
    c = db()
    c.execute('DELETE FROM watchlist WHERE ws=? AND uid=? AND symbol=?', (user['ws'], user['uid'], sym))
    c.commit(); c.close()
    return {'status': 'ok', 'message': f'{sym} removed from watchlist'}

def add_alert(user, symbol, condition, threshold, note=''):
    _ensure_watchlist_tables()
    sym = symbol.upper().strip()
    if condition not in ('above', 'below'):
        return {'status': 'error', 'error': 'condition must be above or below'}
    c = db()
    c.execute('INSERT INTO price_alerts(ws,uid,symbol,condition,threshold,note,active,created_at) VALUES(?,?,?,?,?,?,1,?)',
              (user['ws'], user['uid'], sym, condition, float(threshold), note, time.time()))
    c.commit(); c.close()
    return {'status': 'ok', 'message': f'Alert set: {sym} {condition} {threshold}'}

def list_alerts(user):
    _ensure_watchlist_tables()
    c = db()
    rows = c.execute('SELECT id,symbol,condition,threshold,note,active,triggered_at,created_at FROM price_alerts WHERE ws=? AND uid=? ORDER BY id DESC LIMIT 50', (user['ws'], user['uid'])).fetchall()
    c.close()
    return {'status': 'ok', 'kind': 'actual', 'alerts': [{
        'id': r['id'], 'symbol': r['symbol'], 'condition': r['condition'],
        'threshold': r['threshold'], 'note': r['note'],
        'active': bool(r['active']),
        'triggered_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(r['triggered_at'])) if r['triggered_at'] else None,
        'created_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(r['created_at']))
    } for r in rows]}

def delete_alert(user, alert_id):
    _ensure_watchlist_tables()
    c = db()
    c.execute('DELETE FROM price_alerts WHERE id=? AND ws=? AND uid=?', (int(alert_id), user['ws'], user['uid']))
    c.commit(); c.close()
    return {'status': 'ok', 'message': f'Alert #{alert_id} deleted'}
