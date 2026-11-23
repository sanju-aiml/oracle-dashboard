import os
import sys
import tempfile
import time

_tmp = tempfile.mkdtemp()
os.environ.update(ORACLE_DB=f"{_tmp}/o.db", ORACLE_MODELS=f"{_tmp}/m", ORACLE_UPLOADS=f"{_tmp}/u",
                  ORACLE_GATE_LOG=f"{_tmp}/g.jsonl", ORACLE_ADMIN_TOKEN="secret", ALLOW_SCRAPING="0")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import alerts
import answer
import bot
import notify
import config
import image_model
import market_data as md
import model
import store
import synthetic


def reg(sym, cls="stock"):
    config.ASSETS[sym] = dict(name=sym, cls=cls, aliases=[sym.lower()], yf="X")


def fresh(sym, n=2500, seed=0, phi=0.0):
    with store.db() as c:
        c.execute("DELETE FROM candles WHERE symbol=?", (sym,))
    store.upsert_candles(synthetic.make_candles(n, seed=seed, phi=phi), sym, "1d", "synthetic")


# ---- gate honesty ---------------------------------------------------------------
def test_gate_rejects_random_walks():
    reg("RW")
    passes = 0
    for seed in range(3):
        fresh("RW", seed=seed)
        r = model.train("RW", "1d")
        passes += sum(v["passed"] for v in r.values())
    assert passes == 0


def test_gate_accepts_real_edge():
    reg("MOM")
    fresh("MOM", seed=11, phi=0.5)
    r = model.train("MOM", "1d", horizons=(1,))
    assert r[1]["passed"], r[1]["reasons"]


def test_no_lookahead_in_features():
    df = synthetic.make_candles(300, seed=3)
    import features
    full = features.build_features(df)
    part = features.build_features(df.iloc[:200])
    assert np.allclose(full.iloc[:200].fillna(0).values, part.fillna(0).values, atol=1e-9)


# ---- data layer never invents prices --------------------------------------------------
def test_quote_fallback_chain(monkeypatch):
    reg("QF")
    fresh("QF", n=300)
    calls = []

    def boom():
        calls.append("primary")
        raise RuntimeError("api down")

    last = float(store.load_candles("QF").close.iloc[-1])
    monkeypatch.setattr(md, "_quote_sources", lambda a: [("Primary", boom), ("Backup", lambda: last * 1.001)])
    q = md.get_quote("QF", max_fresh=0)
    assert q["status"] == "backup" and q["source"] == "Backup"

    monkeypatch.setattr(md, "_quote_sources", lambda a: [("Primary", boom), ("Backup", boom)])
    q = md.get_quote("QF", max_fresh=0)
    assert q["status"] == "stale" and q["price"] is not None and q["age_sec"] is not None

    monkeypatch.setattr(md, "_quote_sources", lambda a: [("Primary", lambda: last * 10)])
    q = md.get_quote("QF", max_fresh=0)
    assert q["status"] == "stale"                       # absurd jump rejected, stored price shown


def test_quote_none_when_nothing_stored(monkeypatch):
    reg("EMPTY")
    monkeypatch.setattr(md, "_quote_sources", lambda a: [])
    assert md.get_quote("EMPTY", max_fresh=0)["status"] == "none"


# ---- answers ----------------------------------------------------------------------------
def test_answer_always_from_own_data(monkeypatch):
    config.ASSETS["BTC"]["aliases"] = ["bitcoin", "btc"]
    fresh("BTC", n=1500, seed=5, phi=0.0)
    monkeypatch.setattr(md, "_quote_sources", lambda a: [])        # all APIs down
    monkeypatch.setattr(md, "refresh_candles", lambda *a, **k: (0, None))
    model.train("BTC", "1d", horizons=(1, 5))
    out = answer.answer("Bitcoin future growth? should I invest")
    t = out["answer"]
    assert "Bitcoin" in t and "last stored price" in t and "Next 1 day" in t and "Likely range" in t
    assert "unavailable" not in t.lower() and "cannot tell you to buy or sell" in t
    assert "not financial advice" in t.lower()


def test_answer_unknown_asset_gives_guidance():
    out = answer.answer("what about zzzz widgets?")
    assert "could not match" in out["answer"]


# ---- bot --------------------------------------------------------------------------------
def test_bot_tick_and_accounting(monkeypatch):
    reg("BOTA")
    fresh("BOTA", n=2500, seed=11, phi=0.5)
    config.BOT_SYMBOLS[:] = ["BOTA"]
    model.train("BOTA", "1d", horizons=(1,))
    last = float(store.load_candles("BOTA").close.iloc[-1])
    monkeypatch.setattr(md, "_quote_sources", lambda a: [("T", lambda: last)])
    monkeypatch.setattr(md, "refresh_candles", lambda *a, **k: (0, None))
    monkeypatch.setattr(store, "closed_only", lambda df, interval="1d", now=None: df)
    st = bot.tick(force_refresh=True)
    assert st["last_error"] is None
    s = bot.account_summary()
    assert s["paper_only"] and s["equity"] > 0
    assert abs(s["equity"] - s["cash"]) < s["start_cash"] * 0.01      # fees only, no price move yet
    # kill switch
    with store.db() as c:
        c.execute("UPDATE paper_account SET equity_peak=? WHERE id=1", (s["equity"] * 2,))
    bot._check_drawdown()
    assert bot.account_summary()["halted"]
    bot.resume_bot()
    assert not bot.account_summary()["halted"]


def test_play_call_resolves(monkeypatch):
    reg("PLAY")
    fresh("PLAY", n=100)
    prices = {"p": 100.0}
    monkeypatch.setattr(md, "_quote_sources", lambda a: [("T", lambda: prices["p"])])
    r = bot.record_user_call("u1", "PLAY", "up", "5m")
    assert r["entry_price"] == 100.0
    with store.db() as c:
        c.execute("UPDATE predictions SET resolve_after=? WHERE id=?", (int(time.time()) - 1, r["id"]))
    prices["p"] = 105.0
    with store.db() as c:                               # age the entry quote so it is not reused
        c.execute("UPDATE quotes SET ts=ts-1000 WHERE symbol='PLAY'")
    bot.resolve_predictions()
    h = store.user_history("u1")[0]
    assert h["outcome"] == "win" and abs(h["pnl_pct"] - 5.0) < 1e-6
    # too late => void, never a fake result
    r2 = bot.record_user_call("u1", "PLAY", "down", "5m")
    with store.db() as c:
        c.execute("UPDATE predictions SET resolve_after=? WHERE id=?", (int(time.time()) - 99999, r2["id"]))
    bot.resolve_predictions()
    assert store.user_history("u1")[0]["outcome"] == "void"


# ---- chart image reader -----------------------------------------------------------------
def _chart_png(n=30, seed=1):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    df = synthetic.make_candles(n + 1, seed=seed, phi=0.0).tail(n)
    fig, ax = plt.subplots(figsize=(6, 3), dpi=100)
    ax.set_facecolor("black")
    for i, r in enumerate(df.itertuples()):
        col = "#16c784" if r.close >= r.open else "#ea3943"
        ax.plot([i, i], [r.low, r.high], color=col, lw=1)
        ax.bar(i, r.close - r.open, bottom=r.open, color=col, width=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()


def test_image_reader_reads_candles_and_rejects_junk():
    res = image_model.analyze_image(_chart_png())
    assert res["ok"] and res["raster"].shape == (2, 48, 48) and res["raster"].sum() > 100
    junk = io.BytesIO()
    Image.new("RGB", (200, 200), (120, 120, 120)).save(junk, format="PNG")
    assert not image_model.analyze_image(junk.getvalue())["ok"]
    assert not image_model.analyze_image(b"not an image")["ok"]


def test_image_model_trains_and_is_gated():
    for i in range(3):
        reg(f"IMG{i}")
        fresh(f"IMG{i}", n=1200, seed=20 + i, phi=0.0)
    rep = image_model.train([f"IMG{i}" for i in range(3)])
    assert rep["status"] == "trained" and rep["passed"] is False      # random data: must not pass


# ---- API ---------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def client():
    os.environ["BOT_ENABLED"] = "0"
    import main
    with TestClient(main.app) as c:
        yield c


def test_api_routes(client, monkeypatch):
    reg("API")
    fresh("API", n=500, seed=2)
    lastc = float(store.load_candles("API").close.iloc[-1])
    monkeypatch.setattr(md, "_quote_sources", lambda a: [("T", lambda: lastc)])
    assert client.get("/api/health").json()["ok"]
    r = client.get("/api/market/paper-trade")
    assert r.status_code == 200 and r.json()["paper_only"] is True        # the old 404 route
    assert client.get("/api/market/quote/API").json()["status"] in ("fresh", "backup")
    assert len(client.get("/api/market/candles/API?limit=5").json()["candles"]) == 5
    assert client.get("/api/forecast/API").json()["available"]
    assert client.get("/api/market/quote/NOPE_NOT_REAL").status_code == 404
    a = client.post("/api/ask", json={"question": "api forecast?"}).json()
    assert "Likely range" in a["answer"]
    p = client.post("/api/play/call", json={"user_id": "u9", "symbol": "API", "call": "up", "duration": "5m"})
    assert p.status_code == 200
    assert client.post("/api/play/call", json={"user_id": "u9", "symbol": "API", "call": "sideways"}).status_code == 400
    up = client.post("/api/chart/analyze", files={"file": ("c.png", _chart_png(), "image/png")}, data={"consent": "true"}).json()
    assert up["ok"] and up["image_token"] and "Not financial advice" in up["message"]
    p2 = client.post("/api/play/call", json={"user_id": "u9", "symbol": "API", "call": "down", "duration": "5m",
                                             "image_token": up["image_token"]})
    assert p2.status_code == 200
    assert client.post("/api/admin/resume").status_code in (403, 404)
    assert client.post("/api/admin/bot/resume").status_code == 403
    assert client.post("/api/admin/bot/resume", headers={"X-Admin-Token": "secret"}).status_code == 200
    assert client.get("/").status_code == 200


# ---- alerts -----------------------------------------------------------------------------------
def test_alert_rules_holdings_stress_and_ipo(monkeypatch):
    reg("ALR")
    fresh("ALR", n=400, seed=4)
    last = float(store.load_candles("ALR").close.iloc[-1])
    price = {"p": last}
    monkeypatch.setattr(md, "_quote_sources", lambda a: [("T", lambda: price["p"])])
    sent = []
    monkeypatch.setattr(notify, "_ntfy", lambda topic, title, body, priority="default": sent.append((topic, title, body)))
    notify.set_channel("mom", ntfy_topic="momtopic12345")
    alerts.add_rule("mom", "ALR", "price_below", last * 0.97)
    alerts.set_holding("mom", "ALR", 10, last * 1.2, stop_pct=8, target_pct=15)   # bought 20% higher => deep loss
    alerts.add_ipo("TestCo Ltd", dt_today(), dt_today(), "100-105", "140 shares")

    store.save_quote("ALR", last, "x", ts=1)
    with store.db() as c:
        c.execute("UPDATE quotes SET ts=ts-1000 WHERE symbol='ALR'")
    alerts.evaluate_all()
    titles = [s[1] for s in sent]
    assert not any("falls to or below" in t for t in titles)          # price still above the level
    assert any("Your holding" in t and "DOWN" in t for t in titles)   # holding stop hit
    assert any("IPO opens today" in t for t in titles)
    assert all("not advice" in s[2].lower() for s in sent)

    price["p"] = last * 0.96
    with store.db() as c:
        c.execute("UPDATE quotes SET ts=ts-1000 WHERE symbol='ALR'")
    alerts.evaluate_all()
    assert any("falls to or below" in s[1] for s in sent)
    n = len(sent)
    alerts.evaluate_all()                                              # cooldown: no repeat spam
    assert len(sent) == n
    assert store.load_candles("ALR").shape[0] > 0
    with store.db() as c:
        assert c.execute("SELECT COUNT(*) n FROM alerts_log WHERE user_id='mom'").fetchone()["n"] >= 3


def test_alerts_never_use_stale_price(monkeypatch):
    reg("OLD")
    fresh("OLD", n=400, seed=6)
    last = float(store.load_candles("OLD").close.iloc[-1])
    monkeypatch.setattr(md, "_quote_sources", lambda a: [])             # all sources down
    sent = []
    monkeypatch.setattr(notify, "_ntfy", lambda *a, **k: sent.append(a))
    notify.set_channel("dad", ntfy_topic="dadtopic12345")
    alerts.add_rule("dad", "OLD", "price_below", last * 10)             # would fire if price were trusted
    with store.db() as c:
        c.execute("DELETE FROM quotes WHERE symbol='OLD'")
        c.execute("INSERT INTO quotes VALUES ('OLD', ?, ?, 'x')", (int(time.time()) - 86400, last))
    alerts.evaluate_all()
    assert sent == []


def dt_today():
    import datetime
    return datetime.date.today().isoformat()


# ---- web fallback, market hours, live stream --------------------------------------------------
def test_nse_web_parsing_and_robots(monkeypatch):
    calls = []

    class R:
        def __init__(self, j): self._j = j
        def raise_for_status(self): pass
        def json(self): return self._j

    class S:
        headers = {}
        def __init__(self): self.headers = {}
        def get(self, url, params=None, timeout=None):
            calls.append(url)
            if "quote-equity" in url:
                return R({"priceInfo": {"lastPrice": 2530.5}})
            if "allIndices" in url:
                return R({"data": [{"index": "NIFTY BANK", "last": 1}, {"index": "NIFTY 50", "last": 22497.8}]})
            return R({})
    monkeypatch.setattr(md.requests, "Session", S)
    monkeypatch.setattr(md, "_robots_allows", lambda url: True)
    md._nse["s"] = None
    assert md.q_nse_equity("TCS") == 2530.5
    assert md.q_nse_index("nifty 50") == 22497.8
    with pytest.raises(ValueError):
        md.q_nse_index("NO SUCH")
    monkeypatch.setattr(md, "_robots_allows", lambda url: False)
    with pytest.raises(PermissionError):
        md.q_nse_equity("TCS")


def test_market_state():
    from datetime import datetime, timezone
    u = lambda *a: datetime(*a, tzinfo=timezone.utc)
    config.ASSETS["TCS"]["yf"] = "TCS.NS"
    assert md.market_state("TCS", u(2026, 10, 23, 9, 18)) == "open"      # 14:48 IST Friday (your video)
    assert md.market_state("TCS", u(2026, 10, 23, 11, 0)) == "closed"    # 16:30 IST
    assert md.market_state("TCS", u(2026, 10, 24, 6, 0)) == "closed"     # Saturday
    assert md.market_state("AAPL", u(2026, 10, 23, 12, 18)) == "closed"  # 08:18 New York, before the open
    assert md.market_state("AAPL", u(2026, 10, 23, 15, 0)) == "open"
    assert md.market_state("BTC", u(2026, 10, 24, 6, 0)) == "open"       # crypto never sleeps
    assert md.market_state("XAU", u(2026, 10, 24, 15, 0)) == "closed"    # Saturday futures


def test_quote_carries_market_flag_and_stream(client, monkeypatch):
    reg("LIV")
    fresh("LIV", n=300, seed=8)
    lastc = float(store.load_candles("LIV").close.iloc[-1])
    monkeypatch.setattr(md, "_quote_sources", lambda a: [("T", lambda: lastc)])
    q = md.get_quote("LIV", max_fresh=0)
    assert q["market"] in ("open", "closed")
    with client.stream("GET", "/api/stream/LIV?interval=2&max_events=2") as r:
        lines = [l for l in r.iter_lines() if l.startswith("data:")]
    assert len(lines) == 2 and json.loads(lines[0][5:])["symbol"] == "LIV"
