"""Alert engine: your rules, your holdings, market-stress and IPO reminders.

What alerts DO: tell you, with facts and timestamps, when a price crosses a level YOU chose, when a
holding hits YOUR stop/target, when a stock has dropped hard / looks oversold, when the market is
stressed, and when an IPO you track opens or closes.
What alerts do NOT do: promise profit or call a bottom. A falling price is not automatically a buying
opportunity, so dip alerts say "setup", never "buy"."""
import datetime as dt
import time

import config
import features
import market_data as md
import model
import notify
import store

KINDS = {
    "price_below": "price falls to or below the level",
    "price_above": "price rises to or above the level",
    "drop_from_high": "price is X% or more below its 20-day high",
    "rise_day": "price is up X% or more versus last close",
    "fall_day": "price is down X% or more versus last close",
    "rsi_below": "RSI(14) is at or below the level (oversold zone)",
    "rsi_above": "RSI(14) is at or above the level (overbought zone)",
    "near_52w_low": "price is within X% of its 52-week low",
}


# ---- rule / holding / ipo CRUD ---------------------------------------------------
def add_rule(user_id, symbol, kind, threshold, cooldown_sec=None):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {list(KINDS)}")
    if symbol not in config.ASSETS:
        raise ValueError("unknown symbol")
    with store.db() as c:
        cur = c.execute("INSERT INTO watch_rules(user_id,symbol,kind,threshold,cooldown_sec,created_at) VALUES (?,?,?,?,?,?)",
                        (user_id, symbol, kind, float(threshold), cooldown_sec or config.DEFAULT_COOLDOWN, int(time.time())))
        return cur.lastrowid


def list_rules(user_id):
    with store.db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM watch_rules WHERE user_id=? AND active=1 ORDER BY id", (user_id,))]


def delete_rule(user_id, rule_id):
    with store.db() as c:
        c.execute("UPDATE watch_rules SET active=0 WHERE id=? AND user_id=?", (rule_id, user_id))


def set_holding(user_id, symbol, qty, avg_price, stop_pct=8.0, target_pct=15.0):
    if symbol not in config.ASSETS:
        raise ValueError("unknown symbol")
    with store.db() as c:
        c.execute("INSERT OR REPLACE INTO holdings VALUES (?,?,?,?,?,?)",
                  (user_id, symbol, float(qty), float(avg_price), float(stop_pct), float(target_pct)))


def list_holdings(user_id):
    with store.db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM holdings WHERE user_id=?", (user_id,))]
    for r in rows:
        q = md.get_quote(r["symbol"])
        r["price"] = q["price"]
        r["status"] = q["status"]
        if q["price"]:
            r["pnl_pct"] = (q["price"] / r["avg_price"] - 1) * 100
            r["pnl_abs"] = (q["price"] - r["avg_price"]) * r["qty"]
    return rows


def add_ipo(name, open_date, close_date, price_band="", lot_size="", notes=""):
    with store.db() as c:
        return c.execute("INSERT INTO ipos(name,open_date,close_date,price_band,lot_size,notes) VALUES (?,?,?,?,?,?)",
                         (name, open_date, close_date, price_band, lot_size, notes)).lastrowid


def list_ipos():
    with store.db() as c:
        return [dict(r) for r in c.execute("SELECT * FROM ipos ORDER BY open_date")]


# ---- metrics ----------------------------------------------------------------------------
def metrics(symbol):
    q = md.get_quote(symbol)
    df = store.closed_only(store.load_candles(symbol, "1d"), "1d")
    if q["price"] is None or len(df) < 30:
        return None
    price = q["price"]
    last_close = float(df.close.iloc[-1])
    hi20 = float(df.high.tail(20).max())
    yr = df.tail(252)
    rsi = float(features._rsi(df.close, 14).iloc[-1])
    return {"price": price, "status": q["status"], "source": q["source"], "age_sec": q["age_sec"],
            "day_pct": (price / last_close - 1) * 100,
            "from_high20_pct": (price / hi20 - 1) * 100,
            "above_52w_low_pct": (price / float(yr.low.min()) - 1) * 100,
            "rsi": rsi}


def _test(kind, thr, m):
    return {
        "price_below": m["price"] <= thr,
        "price_above": m["price"] >= thr,
        "drop_from_high": m["from_high20_pct"] <= -abs(thr),
        "rise_day": m["day_pct"] >= abs(thr),
        "fall_day": m["day_pct"] <= -abs(thr),
        "rsi_below": m["rsi"] <= thr,
        "rsi_above": m["rsi"] >= thr,
        "near_52w_low": m["above_52w_low_pct"] <= abs(thr),
    }[kind]


def _facts(sym, m):
    name = config.ASSETS.get(sym, {}).get("name", sym)
    live = "live" if m["status"] in ("fresh", "backup") else f"last stored price ({m['status']})"
    return (f"{name}: {m['price']:,.2f} ({live}; {m['source']}). Day {m['day_pct']:+.2f}%, "
            f"{m['from_high20_pct']:+.1f}% vs 20-day high, RSI {m['rsi']:.0f}, "
            f"{m['above_52w_low_pct']:.1f}% above 52-week low.")


FOOT = "Information only, not advice. Prices can keep moving against you."


# ---- evaluation --------------------------------------------------------------------------
def _fire_rules(cache):
    now = int(time.time())
    with store.db() as c:
        rules = [dict(r) for r in c.execute("SELECT * FROM watch_rules WHERE active=1")]
    for r in rules:
        if now - (r["last_fired"] or 0) < r["cooldown_sec"]:
            continue
        sym = r["symbol"]
        if sym not in config.ASSETS:
            continue
        m = cache.setdefault(sym, metrics(sym))
        if not m or m["status"] == "stale" and m["age_sec"] and m["age_sec"] > 3600:
            continue                     # never alert on an old price as if it were live
        if _test(r["kind"], r["threshold"], m):
            title = f"{config.ASSETS[sym]['name']}: {KINDS[r['kind']]} ({r['threshold']:g})"
            notify.send(r["user_id"], sym, r["kind"], title, _facts(sym, m) + "\n" + FOOT)
            with store.db() as c:
                c.execute("UPDATE watch_rules SET last_fired=? WHERE id=?", (now, r["id"]))


def _fire_holdings(cache):
    now = int(time.time())
    with store.db() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM holdings")]
    for h in rows:
        sym = h["symbol"]
        if sym not in config.ASSETS:
            continue
        m = cache.setdefault(sym, metrics(sym))
        if not m or m["status"] == "stale":
            continue
        pnl = (m["price"] / h["avg_price"] - 1) * 100
        for tag, hit, text in (("stop", pnl <= -h["stop_pct"], f"is DOWN {pnl:.1f}% from your buy price (your stop was {h['stop_pct']:g}%)"),
                               ("target", pnl >= h["target_pct"], f"is UP {pnl:.1f}% from your buy price (your target was {h['target_pct']:g}%)")):
            key = f"hold_{h['user_id']}_{sym}_{tag}"
            if hit and now - store.kv_get(key, 0) > config.DEFAULT_COOLDOWN:
                title = f"Your holding {config.ASSETS[sym]['name']} {text}"
                notify.send(h["user_id"], sym, f"holding_{tag}", title, _facts(sym, m) + "\n" + FOOT, "high" if tag == "stop" else "default")
                store.kv_set(key, now)


def _fire_stress(cache):
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    if store.kv_get("stress_sent") == today:
        return
    nifty = cache.setdefault("NIFTY", metrics("NIFTY")) if "NIFTY" in config.ASSETS else None
    vix = cache.setdefault("INDIAVIX", metrics("INDIAVIX")) if "INDIAVIX" in config.ASSETS else None
    reasons = []
    if nifty and nifty["status"] != "stale" and nifty["day_pct"] <= config.STRESS_NIFTY_DROP:
        reasons.append(f"Nifty is {nifty['day_pct']:+.2f}% today")
    if vix and vix["status"] != "stale" and vix["day_pct"] >= config.STRESS_VIX_JUMP:
        reasons.append(f"India VIX jumped {vix['day_pct']:+.1f}% (fear is rising)")
    if not reasons:
        return
    body = ("; ".join(reasons) + ". Sharp falls can continue before they recover; a falling market is not a "
            "guaranteed buying chance. Avoid rushing, avoid borrowed money, and keep to the limits you set. " + FOOT)
    with store.db() as c:
        users = [r["user_id"] for r in c.execute("SELECT DISTINCT user_id FROM user_channels")]
    for u in users:
        notify.send(u, "NIFTY", "market_stress", "Market stress alert", body, "high")
    store.kv_set("stress_sent", today)


def _fire_setups(cache):
    """Facts-only 'setup' alerts for symbols users watch: sharp drop + oversold, or validated model edge."""
    with store.db() as c:
        pairs = [(r["user_id"], r["symbol"]) for r in c.execute(
            "SELECT DISTINCT user_id, symbol FROM watch_rules WHERE active=1 UNION "
            "SELECT DISTINCT user_id, symbol FROM holdings")]
    now = int(time.time())
    for user, sym in pairs:
        m = cache.setdefault(sym, metrics(sym))
        if not m or m["status"] == "stale":
            continue
        notes = []
        if m["from_high20_pct"] <= -10 and m["rsi"] <= 30:
            notes.append(f"dropped {abs(m['from_high20_pct']):.0f}% from its 20-day high and RSI {m['rsi']:.0f} is in the oversold zone "
                         "(oversold can stay oversold)")
        fc = model.forecast(sym)
        it = fc.get("horizons", {}).get(1) if fc.get("available") else None
        if it and it["gate_passed"] and abs(it["p_up"] - 0.5) >= 0.06:
            d = "up" if it["p_up"] > 0.5 else "down"
            notes.append(f"validated model leans {d} for the next day ({max(it['p_up'], 1 - it['p_up']) * 100:.0f}%)")
        key = f"setup_{user}_{sym}"
        if notes and now - store.kv_get(key, 0) > config.DEFAULT_COOLDOWN * 2:
            notify.send(user, sym, "setup", f"{config.ASSETS.get(sym, {}).get('name', sym)}: setup to review",
                        "; ".join(notes) + ".\n" + _facts(sym, m) + "\n" + FOOT)
            store.kv_set(key, now)


def _fire_ipos():
    today = dt.date.today()
    with store.db() as c:
        users = [r["user_id"] for r in c.execute("SELECT DISTINCT user_id FROM user_channels")]
    for ipo in list_ipos():
        try:
            o = dt.date.fromisoformat(ipo["open_date"])
            cl = dt.date.fromisoformat(ipo["close_date"])
        except Exception:
            continue
        events = []
        if today == o - dt.timedelta(days=1):
            events.append(("opens_tomorrow", f"{ipo['name']} IPO opens tomorrow"))
        if today == o:
            events.append(("opens_today", f"{ipo['name']} IPO opens today"))
        if today == cl:
            events.append(("closes_today", f"{ipo['name']} IPO closes today, last day to apply"))
        for tag, title in events:
            key = f"ipo_{ipo['id']}_{tag}"
            if store.kv_get(key):
                continue
            body = (f"Dates: {ipo['open_date']} to {ipo['close_date']}. Price band: {ipo['price_band'] or 'check offer document'}. "
                    f"Lot: {ipo['lot_size'] or 'check offer document'}. {ipo['notes'] or ''}\n"
                    "Before applying read the RHP/offer document: company profits and debt, what the money is used for, "
                    "valuation versus peers, and how much of the issue is promoter selling. Grey-market premium is not reliable. "
                    "Apply only money you can afford to lock up or lose. " + FOOT)
            for u in users:
                notify.send(u, ipo["name"], "ipo", title, body)
            store.kv_set(key, int(time.time()))


def evaluate_all():
    """Run every alert check once. Called from the bot loop each tick; safe and cheap (quotes are cached)."""
    cache = {}
    for fn in (_fire_rules, _fire_holdings, _fire_stress, _fire_setups):
        fn(cache)
    _fire_ipos()
