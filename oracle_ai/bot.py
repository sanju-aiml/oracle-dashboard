"""24/7 PAPER trading bot + resolver for user "UP/DOWN" calls.

Paper only: virtual money, no broker, no real orders. It trades a symbol only when that symbol's
candle model passed the holdout gate; otherwise it records forecasts but stays out.
Safety rails: 1% risk per trade, 10% max position, max 5 positions, ATR stop/target,
time exit, and a kill switch at -10% drawdown from peak equity.
"""
import asyncio
import logging
import math
import time

import alerts
import config
import market_data as md
import model
import store

log = logging.getLogger("oracle.bot")


# ---- account ---------------------------------------------------------------
def _account(c):
    row = c.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
    if row is None:
        c.execute("INSERT INTO paper_account VALUES (1,?,?,0,NULL,?)",
                  (config.PAPER_START_CASH, config.PAPER_START_CASH, int(time.time())))
        row = c.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
    return dict(row)


def _mark(symbol):
    q = md.get_quote(symbol)
    return q["price"]


def account_summary():
    with store.db() as c:
        acc = _account(c)
        pos = [dict(r) for r in c.execute("SELECT * FROM paper_positions WHERE status='open'").fetchall()]
        closed = [dict(r) for r in c.execute(
            "SELECT * FROM paper_positions WHERE status='closed' ORDER BY id DESC LIMIT 50").fetchall()]
        stats = c.execute("SELECT COUNT(*) n, SUM(pnl>0) w, SUM(pnl) tot FROM paper_positions WHERE status='closed'").fetchone()
    unreal = 0.0
    for p in pos:
        px = (store.latest_quote(p["symbol"]) or {}).get("price") or p["entry_price"]
        p["mark"] = px
        p["unrealized"] = (px - p["entry_price"]) * p["qty"] * (1 if p["side"] == "long" else -1)
        unreal += p["unrealized"]
    equity = acc["cash"] + unreal
    n = stats["n"] or 0
    return {"cash": acc["cash"], "equity": equity, "start_cash": config.PAPER_START_CASH,
            "return_pct": (equity / config.PAPER_START_CASH - 1) * 100,
            "peak_equity": acc["equity_peak"], "halted": bool(acc["halted"]), "halt_reason": acc["halt_reason"],
            "open_positions": pos, "recent_closed": closed,
            "closed_trades": n, "win_rate": (stats["w"] / n) if n else None,
            "realized_pnl": stats["tot"] or 0.0, "paper_only": True,
            "bot": store.kv_get("bot_status", {})}


# ---- trading ---------------------------------------------------------------
def _open_position(symbol, side, price, atr_frac, h):
    asset = config.ASSETS.get(symbol)
    if not asset:
        return None
    cost = config.COST_PER_SIDE.get(asset["cls"], 0.0005)
    with store.db() as c:
        acc = _account(c)
        if acc["halted"]:
            return None
        if c.execute("SELECT COUNT(*) n FROM paper_positions WHERE status='open'").fetchone()["n"] >= config.MAX_OPEN_POSITIONS:
            return None
        if c.execute("SELECT 1 FROM paper_positions WHERE status='open' AND symbol=?", (symbol,)).fetchone():
            return None
        unreal = 0.0
        for p in c.execute("SELECT * FROM paper_positions WHERE status='open'").fetchall():
            px = (store.latest_quote(p["symbol"]) or {}).get("price") or p["entry_price"]
            unreal += (px - p["entry_price"]) * p["qty"] * (1 if p["side"] == "long" else -1)
        equity = acc["cash"] + unreal
        stop_dist = max(price * atr_frac * config.STOP_ATR, price * 0.002)
        qty = (equity * config.RISK_PER_TRADE) / stop_dist
        qty = min(qty, equity * config.MAX_NOTIONAL_FRAC / price)
        if qty <= 0 or not math.isfinite(qty):
            return None
        fee = qty * price * cost
        sign = 1 if side == "long" else -1
        stop = price - sign * stop_dist
        target = price + sign * price * atr_frac * config.TARGET_ATR
        now = int(time.time())
        c.execute("INSERT INTO paper_positions(symbol,side,qty,entry_price,stop,target,opened_at,expire_at,fees) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (symbol, side, qty, price, stop, target, now, now + h * 86400, fee))
        c.execute("UPDATE paper_account SET cash=cash-?, updated_at=? WHERE id=1", (fee, now))
        return qty


def _close_position(c, p, price, reason):
    asset = config.ASSETS.get(p["symbol"])
    cost = config.COST_PER_SIDE.get(asset["cls"] if asset else "stock", 0.0005)
    sign = 1 if p["side"] == "long" else -1
    gross = (price - p["entry_price"]) * p["qty"] * sign
    fee = p["qty"] * price * cost
    pnl = gross - fee - p["fees"]
    now = int(time.time())
    c.execute("UPDATE paper_positions SET status='closed', exit_price=?, closed_at=?, pnl=?, reason=? WHERE id=?",
              (price, now, pnl, reason, p["id"]))
    c.execute("UPDATE paper_account SET cash=cash+?, updated_at=? WHERE id=1", (gross - fee, now))


def manage_positions():
    with store.db() as c:
        positions = [dict(r) for r in c.execute("SELECT * FROM paper_positions WHERE status='open'").fetchall()]
    for p in positions:
        q = md.get_quote(p["symbol"])
        px = q["price"]
        if px is None:
            continue
        now = time.time()
        long_ = p["side"] == "long"
        reason = None
        if (long_ and px <= p["stop"]) or (not long_ and px >= p["stop"]):
            reason = "stop"
        elif (long_ and px >= p["target"]) or (not long_ and px <= p["target"]):
            reason = "target"
        elif now >= p["expire_at"]:
            reason = "time"
        if reason:
            with store.db() as c:
                _close_position(c, p, px, reason)
    _check_drawdown()


def _check_drawdown():
    s = account_summary()
    with store.db() as c:
        peak = max(s["peak_equity"], s["equity"])
        c.execute("UPDATE paper_account SET equity_peak=? WHERE id=1", (peak,))
        if not s["halted"] and peak > 0 and s["equity"] < peak * (1 - config.MAX_DRAWDOWN):
            c.execute("UPDATE paper_account SET halted=1, halt_reason=? WHERE id=1",
                      (f"drawdown over {config.MAX_DRAWDOWN:.0%} from peak",))
            log.warning("paper bot halted by drawdown kill switch")


def resume_bot():
    with store.db() as c:
        _account(c)
        c.execute("UPDATE paper_account SET halted=0, halt_reason=NULL, equity_peak=cash WHERE id=1")


# ---- predictions -----------------------------------------------------------
def _exit_from_candles(symbol, pred):
    df = store.closed_only(store.load_candles(symbol, "1d"), "1d")
    if not len(df):
        return None
    after = df[df.ts > pred["candle_ts"]]
    if len(after) < pred["horizon"]:
        return None
    return float(after.close.iloc[pred["horizon"] - 1])


def resolve_predictions():
    now = time.time()
    for pred in store.open_predictions():
        symbol = pred["symbol"]
        if pred["origin"] == "bot":
            exit_px = _exit_from_candles(symbol, pred)
            if exit_px is None:
                continue
        else:                                           # user play: quote-based, with a lateness limit
            if now < pred["resolve_after"]:
                continue
            if now - pred["resolve_after"] > config.PLAY_LATE_TOLERANCE:
                store.resolve_prediction(pred["id"], None, "void", None)   # too late to price fairly
                continue
            q = md.get_quote(symbol, max_fresh=20)
            if q["status"] not in ("fresh", "backup") or q["price"] is None:
                continue
            exit_px = q["price"]
        entry = pred["entry_price"]
        move = exit_px / entry - 1
        went_up = move > 0
        if exit_px == entry:
            outcome, pnl = "flat", 0.0
        else:
            win = went_up if pred["call"] == "up" else (not went_up)
            outcome = "win" if win else "loss"
            pnl = move * 100 * (1 if pred["call"] == "up" else -1)
        store.resolve_prediction(pred["id"], exit_px, outcome, pnl)


def record_user_call(user_id, symbol, call, duration_key, image_path=None, raster_path=None, consent=False):
    if symbol not in config.ASSETS:
        raise ValueError("unknown symbol")
    if call not in ("up", "down"):
        raise ValueError("call must be up or down")
    if duration_key not in config.PLAY_DURATIONS:
        raise ValueError(f"duration must be one of {list(config.PLAY_DURATIONS)}")
    q = md.get_quote(symbol, max_fresh=20)
    if q["status"] not in ("fresh", "backup") or q["price"] is None:
        raise RuntimeError("No live price right now, so a fair entry price is not possible. Try again shortly.")
    dur = config.PLAY_DURATIONS[duration_key]
    now = int(time.time())
    pid = store.add_prediction(origin="user", user_id=user_id, symbol=symbol, interval=None, horizon=None,
                               duration_sec=dur, made_at=now, candle_ts=None, entry_price=q["price"], p_up=None,
                               call=call, resolve_after=now + dur, image_path=image_path,
                               raster_path=raster_path, consent=int(bool(consent)))
    return {"id": pid, "symbol": symbol, "call": call, "entry_price": q["price"], "price_source": q["source"],
            "resolves_at": now + dur, "status": q["status"]}


def _issue_bot_predictions():
    for sym in config.BOT_SYMBOLS:
        if sym not in config.ASSETS:
            continue
        try:
            n, _ = md.refresh_candles(sym, "1d", bars=40)
            df = store.closed_only(store.load_candles(sym, "1d"), "1d")
            if len(df) < 60:
                continue
            cts = int(df.ts.iloc[-1])
            seen = store.kv_get(f"bot_pred_{sym}", 0)
            if cts <= seen:
                continue
            fc = model.forecast(sym)
            if not fc.get("available"):
                continue
            for h, item in fc["horizons"].items():
                call = "up" if item["p_up"] >= 0.5 else "down"
                store.add_prediction(origin="bot", user_id=None, symbol=sym, interval="1d", horizon=h,
                                     duration_sec=None, made_at=int(time.time()), candle_ts=cts,
                                     entry_price=fc["last_close"], p_up=item["p_up"], call=call,
                                     resolve_after=None, consent=0)
                edge = abs(item["p_up"] - 0.5)
                if item["gate_passed"] and h == 1 and edge >= config.ENTRY_EDGE:
                    price = md.get_quote(sym)["price"] or fc["last_close"]
                    _open_position(sym, "long" if call == "up" else "short", price, fc["daily_vol"], h)
            store.kv_set(f"bot_pred_{sym}", cts)
        except Exception as e:                      # one bad symbol must never stop the bot
            log.exception("bot step failed for %s: %s", sym, e)


def tick(force_refresh=False):
    """One cycle. Safe to call repeatedly; heavy work runs only when due."""
    now = time.time()
    status = store.kv_get("bot_status", {})
    status["last_tick"] = int(now)
    try:
        resolve_predictions()
        manage_positions()
        try:
            alerts.evaluate_all()
        except Exception as e:                      # alert problems must never stop trading logic
            log.exception("alerts failed")
            status["alerts_error"] = f"{type(e).__name__}: {e}"
        if force_refresh or now - status.get("last_refresh", 0) >= config.BOT_REFRESH_SEC:
            _issue_bot_predictions()
            status["last_refresh"] = int(time.time())
        status["last_error"] = None
    except Exception as e:
        log.exception("bot tick failed")
        status["last_error"] = f"{type(e).__name__}: {e}"
    status["ticks"] = status.get("ticks", 0) + 1
    store.kv_set("bot_status", status)
    return status


async def run_forever(stop_event: asyncio.Event):
    """24/7 loop. Exceptions are logged and the loop continues with backoff."""
    backoff = 1
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(tick)
            backoff = 1
            await asyncio.wait_for(stop_event.wait(), timeout=config.BOT_POLL_SEC)
        except asyncio.TimeoutError:
            continue
        except Exception:
            log.exception("bot loop error; retrying in %ss", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)
