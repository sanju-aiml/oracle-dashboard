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
        r = await ac.get("/api/market/ipos")
        assert r.status_code == 200
        ipos = r.json()["ipos"]
        assert len(ipos) >= 3

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
