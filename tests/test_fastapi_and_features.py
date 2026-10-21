import os, sys, pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from httpx import AsyncClient, ASGITransport
import server, core, market, billing, automations

@pytest.mark.asyncio
async def test_fastapi_health_and_demo():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        r = await ac.get("/api/demo")
        assert r.status_code == 200
        data = r.json()
        assert "SYNTHETIC" in data["label"]
        assert len(data["kpis"]) >= 3
        assert len(data["agents"]) >= 5
        assert "forecast" in data

@pytest.mark.asyncio
async def test_fastapi_calculators():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        r = await ac.post("/api/calc/sip", json={"monthly": 10000, "annual_pct": 12, "years": 10})
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "calculated"
        assert d["invested"] == 1200000

        r = await ac.post("/api/calc/sip", json={"monthly": 10000, "annual_pct": 12, "years": 10, "step_up_pct": 10})
        assert r.status_code == 200
        d = r.json()
        assert d["invested"] > 1200000

        r = await ac.post("/api/calc/swp", json={"corpus": 5000000, "monthly": 30000, "annual_pct": 8, "years": 10})
        assert r.status_code == 200
        assert r.json()["kind"] == "calculated"

        r = await ac.post("/api/calc/lic", json={"annual_premium": 50000, "premium_years": 10, "term_years": 20, "maturity_amount": 1000000})
        assert r.status_code == 200
        assert "effective_return_pct" in r.json()

@pytest.mark.asyncio
async def test_fastapi_market_and_cricket():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        # Live mode: returns honest not_configured when no official exchange filing API is connected
        r = await ac.get("/api/market/ipos")
        assert r.status_code == 200
        assert r.json()["feed_status"] == "not_configured"

        # Demo mode: returns isolated synthetic fixtures clearly labeled
        r_demo = await ac.get("/api/market/ipos?mode=demo")
        assert r_demo.status_code == 200
        assert r_demo.json()["kind"] == "synthetic"
        assert len(r_demo.json()["ipos"]) >= 3

        r = await ac.post("/api/cricket/simulate", json={
            "team1": "India", "team2": "Australia", "format": "T20",
            "target": 185, "current_runs": 120, "wickets_down": 3, "overs_completed": 14.0
        })
        assert r.status_code == 200
        sim = r.json()
        assert "win_probability" in sim
        assert "advisory_notes" in sim

@pytest.mark.asyncio
async def test_fastapi_billing_and_automations():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        r = await ac.get("/api/billing/plans")
        assert r.status_code == 200
        assert len(r.json()["plans"]) == 3

        r = await ac.get("/api/automations/queue")
        assert r.status_code == 200
        assert "pending_actions" in r.json()

        r = await ac.get("/api/automations/rules")
        assert r.status_code == 200
        assert len(r.json()["rules"]) >= 3

@pytest.mark.asyncio
async def test_fastapi_investment_and_alpaca():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        r = await ac.get("/api/market/invest?symbol=AMZN&horizon_days=90&capital=100000")
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "forecast"
        assert "win_probability_pct" in d
        assert "scenarios" in d

        r_oil = await ac.get("/api/market/commodity?name=oil")
        assert r_oil.status_code == 200
        assert r_oil.json()["status"] == "ok"

        r_alpaca = await ac.get("/api/market/alpaca/account")
        assert r_alpaca.status_code == 200
        assert r_alpaca.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_fastapi_new_market_intelligence():
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        # Profile
        r_prof = await ac.get("/api/market/profile?symbol=AAPL")
        assert r_prof.status_code == 200
        assert r_prof.json().get("kind") in ("actual", None) or "status" in r_prof.json()

        # News
        r_news = await ac.get("/api/market/news?symbol=AAPL&count=3")
        assert r_news.status_code == 200
        assert "news" in r_news.json()

        # Forex
        r_fx = await ac.get("/api/market/forex?from_currency=USD&to_currency=INR")
        assert r_fx.status_code == 200
        assert "status" in r_fx.json()

        # Crypto
        r_crypto = await ac.get("/api/market/crypto?symbol=BTC")
        assert r_crypto.status_code == 200
        assert "status" in r_crypto.json()

        # Web Search
        r_search = await ac.get("/api/search?q=Apple+stock+earnings")
        assert r_search.status_code == 200
        assert "results" in r_search.json()

        # Chat with Web/Realtime queries
        r_chat = await ac.post("/api/chat", json={"message": "what is bitcoin price"})
        assert r_chat.status_code == 200
        assert "reply" in r_chat.json()
        assert len(r_chat.json()["reply"]) > 10
