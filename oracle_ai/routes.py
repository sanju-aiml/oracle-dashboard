"""FastAPI router. In your existing ORACLE app:  app.include_router(routes.router)"""
import asyncio
import collections
import json
import os
import re
import secrets
import threading
import time

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import alerts
import answer as answer_mod
import bot
import notify
import config
import image_model
import market_data as md
import model
import store

router = APIRouter(prefix="/api")

# ---- tiny in-memory rate limiter (per IP) -----------------------------------
_hits = collections.defaultdict(collections.deque)
_hits_lock = threading.Lock()


def limiter(per_minute):
    def dep(request: Request):
        ip = request.client.host if request.client else "?"
        key = (ip, request.url.path)
        now = time.time()
        with _hits_lock:
            q = _hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= per_minute:
                raise HTTPException(429, "Too many requests. Please wait a minute.")
            q.append(now)
    return dep


def admin(x_admin_token: str = Header(default="")):
    if not config.ADMIN_TOKEN or not secrets.compare_digest(x_admin_token, config.ADMIN_TOKEN):
        raise HTTPException(403, "admin only")


def _sym(s):
    s = md.normalize_symbol(s)
    if s not in config.ASSETS:
        got = md.register_dynamic(s) if re.fullmatch(r"[A-Z0-9.\-\^=]{1,12}", s) else None
        if not got:
            raise HTTPException(404, f"unknown symbol {s}")
        s = got
    return s


# ---- models ---------------------------------------------------------------------
class AskIn(BaseModel):
    question: str


class PlayIn(BaseModel):
    user_id: str
    symbol: str
    call: str                    # "up" | "down"
    duration: str = "1h"         # 5m | 15m | 1h | 1d
    image_token: str | None = None


# ---- market -----------------------------------------------------------------------
@router.get("/health")
def health():
    return {"ok": True, "bot": store.kv_get("bot_status", {}), "time": int(time.time())}


@router.get("/market/symbols")
def symbols():
    return [{"symbol": s, "name": a["name"], "class": a["cls"]} for s, a in config.ASSETS.items()]


@router.get("/market/quote/{symbol:path}", dependencies=[Depends(limiter(120))])
async def quote(symbol: str):
    return await asyncio.to_thread(md.get_quote, _sym(symbol))


@router.get("/market/candles/{symbol:path}", dependencies=[Depends(limiter(60))])
async def candles(symbol: str, interval: str = "1d", limit: int = 200):
    if interval not in config.INTERVAL_SEC:
        raise HTTPException(400, "interval must be 1d or 1h")
    sym = _sym(symbol)
    df = await asyncio.to_thread(store.load_candles, sym, interval, min(max(limit, 1), 2000))
    return {"symbol": sym, "interval": interval, "candles": df.to_dict("records")}


@router.get("/forecast/{symbol:path}", dependencies=[Depends(limiter(60))])
async def forecast(symbol: str):
    sym = _sym(symbol)

    def work():
        if len(store.load_candles(sym, "1d")) < 60:
            md.seed_history(sym, "1d", 1500)
        return model.forecast(sym)
    return await asyncio.to_thread(work)


@router.post("/ask", dependencies=[Depends(limiter(30))])
async def ask(body: AskIn):
    if len(body.question) > 500:
        raise HTTPException(400, "question too long")
    return await asyncio.to_thread(answer_mod.answer, body.question)


@router.get("/market/paper-trade")
async def paper_trade():
    """Paper-trading account (virtual money). Fixes the 404 on /api/market/paper-trade."""
    return await asyncio.to_thread(bot.account_summary)


# ---- chart images ------------------------------------------------------------------
_TOKEN = re.compile(r"^[0-9a-f]{16}$")


@router.post("/chart/analyze", dependencies=[Depends(limiter(20))])
async def chart_analyze(file: UploadFile = File(...), consent: bool = Form(False)):
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, "image larger than 8 MB")
    res = await asyncio.to_thread(image_model.analyze_image, data)
    if not res["ok"]:
        return {"ok": False, "reason": res["reason"]}
    token = secrets.token_hex(8)
    ras = res.pop("raster")
    np.save(os.path.join(config.UPLOAD_DIR, f"{token}.npy"), ras)     # small raster, used only for training labels
    if consent:                                                         # original image kept only with consent
        with open(os.path.join(config.UPLOAD_DIR, f"{token}.img"), "wb") as fh:
            fh.write(data)
    p = res["p_up"]
    res["p_down"] = 1 - p
    res["image_token"] = token
    res["message"] = (
        f"Chart read. Up {p * 100:.0f}% / Down {(1 - p) * 100:.0f}% for the next candle. "
        + ("The image model passed validation on unseen charts." if res["validated"]
           else "The image model has NOT proven an edge, so treat this as close to a coin flip.")
        + " Not financial advice.")
    return res


# ---- play: press UP or DOWN -------------------------------------------------------------
@router.post("/play/call", dependencies=[Depends(limiter(30))])
async def play_call(body: PlayIn):
    sym = _sym(body.symbol)
    ras_path = img_path = None
    if body.image_token:
        if not _TOKEN.match(body.image_token):
            raise HTTPException(400, "bad image token")
        base = os.path.join(config.UPLOAD_DIR, body.image_token)
        ras_path = base + ".npy" if os.path.exists(base + ".npy") else None
        img_path = base + ".img" if os.path.exists(base + ".img") else None
    try:
        return await asyncio.to_thread(bot.record_user_call, body.user_id[:64], sym, body.call.lower(),
                                       body.duration, img_path, ras_path, bool(img_path))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@router.get("/play/history", dependencies=[Depends(limiter(60))])
async def play_history(user_id: str):
    hist = await asyncio.to_thread(store.user_history, user_id[:64])
    stats = await asyncio.to_thread(store.prediction_stats, "user", user_id[:64])
    return {"stats": stats, "history": hist}


@router.get("/bot/status")
def bot_status():
    s = store.kv_get("bot_status", {})
    s["bot_live_record"] = store.prediction_stats(origin="bot")
    angel_status = store.kv_get("angel_one_status")
    if angel_status:
        s["angel_one"] = angel_status
    elif not os.getenv("ANGEL_API_KEY"):
        s["angel_one"] = "Angel One login failed (credentials not configured in .env)"
    return s


# ---- admin -------------------------------------------------------------------------------
@router.post("/admin/seed", dependencies=[Depends(admin)])
async def admin_seed(symbols: str = ""):
    syms = [s for s in symbols.split(",") if s] or list(config.ASSETS)
    out = {}
    for s in syms:
        if s in config.ASSETS:
            out[s] = await asyncio.to_thread(md.seed_history, s, "1d", 2000)
    return out


@router.post("/admin/train", dependencies=[Depends(admin)])
async def admin_train(symbols: str = ""):
    syms = [s for s in symbols.split(",") if s] or list(config.ASSETS)

    def work():
        for s in syms:
            if s in config.ASSETS:
                model.train(s, "1d")
    threading.Thread(target=work, daemon=True).start()
    return {"started": syms, "watch": "gate_log.jsonl"}


@router.post("/admin/bot/resume", dependencies=[Depends(admin)])
def admin_resume():
    bot.resume_bot()
    return {"ok": True}


# ---- alerts, holdings, IPOs ------------------------------------------------------------------
class RuleIn(BaseModel):
    user_id: str
    symbol: str
    kind: str
    threshold: float
    cooldown_hours: float | None = None


class ChannelIn(BaseModel):
    user_id: str
    ntfy_topic: str | None = None
    telegram_chat_id: str | None = None


class HoldingIn(BaseModel):
    user_id: str
    symbol: str
    qty: float
    avg_price: float
    stop_pct: float = 8.0
    target_pct: float = 15.0


class IpoIn(BaseModel):
    name: str
    open_date: str          # YYYY-MM-DD
    close_date: str
    price_band: str = ""
    lot_size: str = ""
    notes: str = ""


@router.get("/alerts/kinds")
def alert_kinds():
    return alerts.KINDS


@router.post("/alerts/rules", dependencies=[Depends(limiter(30))])
def add_rule(b: RuleIn):
    try:
        rid = alerts.add_rule(b.user_id[:64], _sym(b.symbol), b.kind, b.threshold,
                              int(b.cooldown_hours * 3600) if b.cooldown_hours else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"id": rid}


@router.get("/alerts/rules")
def get_rules(user_id: str):
    return alerts.list_rules(user_id[:64])


@router.delete("/alerts/rules/{rule_id}")
def del_rule(rule_id: int, user_id: str):
    alerts.delete_rule(user_id[:64], rule_id)
    return {"ok": True}


@router.post("/alerts/channel", dependencies=[Depends(limiter(20))])
def set_channel(b: ChannelIn):
    if b.ntfy_topic and not re.fullmatch(r"[A-Za-z0-9_\-]{8,64}", b.ntfy_topic):
        raise HTTPException(400, "ntfy topic: 8-64 letters/digits/-/_ . Use a long random name; anyone who knows it can read it.")
    notify.set_channel(b.user_id[:64], b.ntfy_topic, b.telegram_chat_id)
    return {"ok": True}


@router.post("/alerts/test", dependencies=[Depends(limiter(5))])
async def test_alert(user_id: str):
    d = await asyncio.to_thread(notify.send, user_id[:64], "TEST", "test", "ORACLE test alert",
                                "If you can read this on your phone, alerts are working.")
    return {"delivered": d}


@router.get("/alerts/log")
def alert_log(user_id: str, limit: int = 50):
    with store.db() as c:
        rows = c.execute("SELECT ts,symbol,kind,title,body,delivered FROM alerts_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                         (user_id[:64], min(limit, 200))).fetchall()
    return [dict(r) for r in rows]


@router.post("/holdings", dependencies=[Depends(limiter(30))])
def set_holding(b: HoldingIn):
    try:
        alerts.set_holding(b.user_id[:64], _sym(b.symbol), b.qty, b.avg_price, b.stop_pct, b.target_pct)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.get("/holdings")
async def get_holdings(user_id: str):
    return await asyncio.to_thread(alerts.list_holdings, user_id[:64])


@router.get("/ipos")
def get_ipos():
    return alerts.list_ipos()


@router.post("/admin/ipos", dependencies=[Depends(admin)])
def admin_add_ipo(b: IpoIn):
    return {"id": alerts.add_ipo(b.name, b.open_date, b.close_date, b.price_band, b.lot_size, b.notes)}


# ---- live stream: the page updates by itself, no refresh -----------------------------------
@router.get("/stream/{symbol:path}", dependencies=[Depends(limiter(20))])
async def stream(symbol: str, request: Request, interval: float = 5.0, max_events: int | None = None):
    """Server-Sent Events. One shared store means 1000 viewers cost the same data-source calls as one:
    prices are re-fetched at most once per `interval` seconds per symbol."""
    sym = _sym(symbol)
    interval = min(max(interval, 2.0), 60.0)

    async def gen():
        n = 0
        while not await request.is_disconnected():
            q = await asyncio.to_thread(md.get_quote, sym, interval)
            yield f"data: {json.dumps(q)}\n\n"
            n += 1
            if max_events and n >= max_events:
                break
            await asyncio.sleep(interval)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
