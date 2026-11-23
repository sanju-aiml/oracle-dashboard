import socket
import os, json, mimetypes, time, base64
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import core, market, billing, automations

# Load environment variables
for line in (open(".env").read().splitlines() if os.path.exists(".env") else []):
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

core.SECRET = os.environ.get("ORACLE_SECRET", "change-me-in-env").encode()
try:
    core.migrate()
except Exception as _mig_err:
    print(f"[ORACLE] Startup migration notice: {_mig_err}")
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

paper_trader = market.PaperTradingEngine(1000000.0)

# ==========================================
# 1. Standard Library Handler (Backward-compatible for tests & zero-dependency)
# ==========================================
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, obj, ctype="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        view = memoryview(b)
        for i in range(0, len(b), 16384):
            self.wfile.write(view[i:i+16384])
        try:
            self.wfile.flush()
            self.connection.shutdown(socket.SHUT_WR)
        except Exception:
            pass
        self.close_connection = True
        
    def user(self):
        auth_header = self.headers.get("Authorization", "")
        token = auth_header[7:] if auth_header.startswith("Bearer ") else auth_header
        return core.verify(token)
        
    def handle_any(self, method):
        u = urlparse(self.path); p = u.path; q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}") if method == "POST" else {}
            
            if not p.startswith("/api/"):
                f = os.path.join(STATIC, "index.html" if p == "/" else p.lstrip("/"))
                if not os.path.abspath(f).startswith(STATIC) or not os.path.isfile(f):
                    return self.send(404, {"error": "not found"})
                with open(f, "rb") as fh:
                    return self.send(200, fh.read(), mimetypes.guess_type(f)[0] or "text/plain")
                    
            r = p[5:]
            if r == "demo": return self.send(200, core.dashboard(core.demo_df(), "SYNTHETIC DEMO DATA: not real business data"))
            if r == "auth/register": return self.send(200, core.register(body.get("email", ""), body.get("password", "")))
            if r == "auth/login": return self.send(200, core.login(body.get("email", ""), body.get("password", "")))
            
            if r.startswith("calc/"):
                c_type = r[5:]
                if c_type == "sip":
                    return self.send(200, core.sip(float(body["monthly"]), float(body["annual_pct"]), float(body["years"])))
                elif c_type == "step-up-sip":
                    return self.send(200, core.step_up_sip(float(body["monthly"]), float(body["annual_pct"]), float(body["years"]), float(body.get("step_up_pct", 10.0))))
                elif c_type == "swp":
                    return self.send(200, core.swp(float(body["corpus"]), float(body["monthly"]), float(body["annual_pct"]), float(body["years"])))
                elif c_type == "lic":
                    return self.send(200, core.lic(float(body["annual_premium"]), float(body["premium_years"]), float(body["term_years"]), float(body["maturity_amount"])))
                elif c_type == "fd":
                    return self.send(200, core.fd_calculator(float(body["principal"]), float(body["annual_pct"]), float(body["years"])))
                elif c_type == "rd":
                    return self.send(200, core.rd_calculator(float(body["monthly"]), float(body["annual_pct"]), float(body["months"])))
                elif c_type == "gst":
                    return self.send(200, core.gst_invoice_calc(body.get("items", []), float(body.get("gst_rate", 18.0)), bool(body.get("is_interstate", False))))
                else:
                    return self.send(404, {"error": "unknown calculator"})
                    
            if r == "market/health":
                return self.send(200, market.get_provider_health())
            if r == "market/quote":
                return self.send(200, market.get_live_quote(q.get("kind", "stock"), q.get("symbol", ""), mode=q.get("mode", "live")))
            if r == "market/forecast":
                return self.send(200, core.market_forecast(q.get("symbol", "")))
            if r == "market/ipos":
                return self.send(200, market.get_ipos(mode=q.get("mode", "live")))
            if r == "market/invest":
                sym = q.get("symbol") or body.get("symbol", "AMZN")
                h_d = int(q.get("horizon_days") or body.get("horizon_days", 90))
                cap = float(q.get("capital") or body.get("capital", 100000))
                return self.send(200, market.analyze_investment(sym, h_d, cap))
            if r == "market/commodity":
                return self.send(200, market.get_live_commodity(q.get("name", "gold"), mode=q.get("mode", "live")))
            if r == "market/alpaca/account":
                return self.send(200, market.get_alpaca_account())
            if r == "market/alpaca/positions":
                return self.send(200, market.get_alpaca_positions())
            if r == "market/alpaca/order":
                try:
                    q_val = int(body.get("qty", 1))
                    if q_val <= 0:
                        return self.send(400, {"error": "Order quantity must be strictly greater than 0"})
                except Exception:
                    return self.send(400, {"error": "Invalid quantity"})
                return self.send(200, market.place_alpaca_order(body.get("symbol", "AMZN"), q_val, body.get("side", "buy"), client_order_id=body.get("client_order_id")))
            if r == "market/paper-trade":
                act = body.get("action", "summary")
                if act == "summary":
                    return self.send(200, paper_trader.get_summary())
                return self.send(200, paper_trader.execute_trade(body.get("symbol", ""), act, body.get("shares", 0), float(body.get("price", 0))))
                
            if r == "market/ohlcv":
                return self.send(200, market.get_ohlcv(q.get("symbol", "AMZN"), q.get("interval", "1day"), int(q.get("outputsize", 60)), mode=q.get("mode", "live")))
            if r == "market/crypto":
                return self.send(200, market.get_crypto_price(q.get("symbol", "BTC")))
            if r == "market/forex":
                return self.send(200, market.get_forex(q.get("from", "USD"), q.get("to", "INR")))
            if r == "market/india":
                return self.send(200, market.get_india_index(q.get("index", "NIFTY 50")))
            if r.startswith("market/naturalgas"):
                return self.send(200, market.get_natural_gas())
            if r == "market/profile":
                return self.send(200, market.get_company_profile(q.get("symbol", "AAPL")))
            if r == "market/news":
                return self.send(200, market.get_company_news(q.get("symbol", "AAPL"), int(q.get("count", 5))))
            if r == "market/metrics":
                return self.send(200, market.get_stock_metrics(q.get("symbol", "AAPL")))
            if r == "market/overview":
                return self.send(200, market.get_market_overview())
            if r == "search":
                return self.send(200, market.web_search(q.get("q", "")))
            if r == "watchlist":
                usr = self.user()
                if not usr: return self.send(401, {"error": "Please sign in"})
                if method == "POST":
                    return self.send(200, core.add_to_watchlist(usr, body.get("symbol", ""), body.get("note", "")))
                elif method == "DELETE":
                    return self.send(200, core.remove_from_watchlist(usr, q.get("symbol") or body.get("symbol", "")))
                return self.send(200, core.get_watchlist(usr))
            if r == "alerts":
                usr = self.user()
                if not usr: return self.send(401, {"error": "Please sign in"})
                if method == "POST":
                    return self.send(200, core.add_alert(usr, body.get("symbol", ""), body.get("condition", "above"), float(body.get("threshold", 0)), body.get("note", "")))
                elif method == "DELETE":
                    return self.send(200, core.delete_alert(usr, int(q.get("id") or body.get("id", 0))))
                return self.send(200, core.list_alerts(usr))

            if r == "finllm/status":
                import finllm_engine
                return self.send(200, finllm_engine.get_model_status())
            if r == "finllm/signal":
                import finllm_engine
                return self.send(200, finllm_engine.predict_signal(q.get("symbol", "AMZN"), mode=q.get("mode", "live")))
            if r == "finllm/deeplob":
                import finllm_engine
                return self.send(200, finllm_engine.run_deeplob_signal(q.get("symbol", "AMZN")))
            if r == "finllm/calc":
                import finllm_engine
                body = self.body()
                return self.send(200, finllm_engine.calculate_ca_banking(body.get("type", ""), body.get("params", {})))
            if r == "finllm/chat":
                import finllm_engine
                body = self.body()
                user = self.user()
                u_name = user["username"] if user else "Guest Investor"
                return self.send(200, finllm_engine.run_finllm_agent(body.get("message", ""), user_name=u_name))
            if r == "finllm/status":
                import finllm_engine
                return self.send(200, finllm_engine.get_model_status())
            if r == "finllm/signal":
                import finllm_engine
                return self.send(200, finllm_engine.predict_signal(q.get("symbol", "AMZN"), mode=q.get("mode", "live")))
            if r == "finllm/deeplob":
                import finllm_engine
                return self.send(200, finllm_engine.run_deeplob_signal(q.get("symbol", "AMZN")))
            if r == "finllm/calc":
                import finllm_engine
                body = self.body()
                return self.send(200, finllm_engine.calculate_ca_banking(body.get("type", ""), body.get("params", {})))
            if r == "finllm/chat":
                import finllm_engine
                body = self.body()
                user = self.user()
                u_name = user["username"] if user else "Guest Investor"
                return self.send(200, finllm_engine.run_finllm_agent(body.get("message", ""), user_name=u_name))
            if r == "cricket":
                return self.send(200, core.cricket())
            if r == "cricket/simulate":
                return self.send(200, market.cricket_match_simulator(
                    body.get("team1", "India"), body.get("team2", "Australia"),
                    body.get("format", "T20"), float(body.get("target", 180)),
                    float(body.get("current_runs", 110)), int(body.get("wickets_down", 3)),
                    float(body.get("overs_completed", 13.2))
                ))
                
            if r == "inventory":
                return self.send(200, core.get_inventory_analysis())
            if r == "billing/plans":
                return self.send(200, billing.get_plans())
            if r == "billing/subscribe":
                usr = self.user()
                if not usr: return self.send(401, {"error": "Please sign in"})
                return self.send(200, billing.generate_invoice(usr.get("email", "client@corp.in"), body.get("plan_id", "pro"), usr["ws"]))
                
            if r == "automations/queue":
                return self.send(200, automations.automations.list_queue())
            if r == "automations/rules":
                return self.send(200, automations.automations.list_rules())
            if r == "automations/action":
                usr = self.user()
                if not usr: return self.send(401, {"error": "Please sign in"})
                if body.get("decision") == "approve":
                    return self.send(200, automations.automations.approve_action(body.get("action_id"), usr["role"]))
                return self.send(200, automations.automations.reject_action(body.get("action_id"), usr["role"]))
                
            if r == "audit-trail":
                usr = self.user()
                if not usr: return self.send(401, {"error": "Please sign in"})
                return self.send(200, {"kind": "actual", "logs": core.get_audit_trail(usr)})
                
            if r == "chat":
                usr = self.user()
                d_ctx = core.workspace_dashboard(usr) if usr else core.dashboard(core.demo_df(), "demo")
                return self.send(200, {"reply": core.chat(body.get("message", ""), d_ctx)})
                
            usr = self.user()
            if not usr: return self.send(401, {"error": "Please sign in"})
            if r == "dashboard": return self.send(200, core.workspace_dashboard(usr))
            if r == "upload":
                raw_csv = body.get("csv", "")
                if not raw_csv and "base64_xlsx" in body:
                    xlsx_bytes = base64.b64decode(body["base64_xlsx"])
                    df = core.parse_excel_bytes(xlsx_bytes)
                    csv_io = io.StringIO()
                    df.to_csv(csv_io, index=False)
                    raw_csv = csv_io.getvalue()
                core.save_dataset(usr, body.get("name", "upload.csv"), raw_csv)
                return self.send(200, {"ok": True})
                
            self.send(404, {"error": "unknown route"})
        except PermissionError as e: self.send(403, {"error": str(e)})
        except (ValueError, KeyError, TypeError) as e: self.send(400, {"error": str(e) or "Bad request"})
        except Exception as e: self.send(500, {"error": "Server error", "detail": type(e).__name__})

    def do_GET(self): self.handle_any("GET")
    def do_POST(self): self.handle_any("POST")

# ==========================================
# 2. FastAPI Application (Phase P1 Migration)
# ==========================================
try:
    from fastapi import FastAPI, Header, HTTPException, Depends, Request
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
    from typing import Optional, List, Dict, Any

    app = FastAPI(
        title="ORACLE Decision Intelligence Suite",
        description="Production-grade AI Business Forecasting & Financial Workspace",
        version="2.0.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def get_current_user(authorization: Optional[str] = Header(None)):
        if not authorization:
            return None
        token = authorization[7:] if authorization.startswith("Bearer ") else authorization
        user = core.verify(token)
        return user

    def require_user(authorization: Optional[str] = Header(None)):
        user = get_current_user(authorization)
        if not user:
            raise HTTPException(status_code=401, detail="Please sign in")
        return user

    @app.get("/api/demo")
    def api_demo():
        return core.dashboard(core.demo_df(), "SYNTHETIC DEMO DATA: not real business data")

    @app.get("/api/dashboard")
    def api_dashboard(user=Depends(require_user)):
        return core.workspace_dashboard(user)

    class AuthPayload(BaseModel):
        email: str
        password: str

    @app.post("/api/auth/register")
    def api_register(p: AuthPayload):
        try:
            return core.register(p.email, p.password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/auth/login")
    def api_login(p: AuthPayload):
        try:
            return core.login(p.email, p.password)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    class UploadPayload(BaseModel):
        name: str = "upload.csv"
        csv: Optional[str] = ""
        base64_xlsx: Optional[str] = None

    @app.post("/api/upload")
    def api_upload(p: UploadPayload, user=Depends(require_user)):
        try:
            raw_csv = p.csv or ""
            if not raw_csv and p.base64_xlsx:
                xlsx_bytes = base64.b64decode(p.base64_xlsx)
                df = core.parse_excel_bytes(xlsx_bytes)
                buf = io.StringIO()
                df.to_csv(buf, index=False)
                raw_csv = buf.getvalue()
            core.save_dataset(user, p.name, raw_csv)
            return {"ok": True}
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    class SipPayload(BaseModel):
        monthly: float
        annual_pct: float
        years: float
        step_up_pct: Optional[float] = 0.0

    @app.post("/api/calc/sip")
    def api_sip(p: SipPayload):
        try:
            if p.step_up_pct and p.step_up_pct > 0:
                return core.step_up_sip(p.monthly, p.annual_pct, p.years, p.step_up_pct)
            return core.sip(p.monthly, p.annual_pct, p.years)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    class SwpPayload(BaseModel):
        corpus: float
        monthly: float
        annual_pct: float
        years: float

    @app.post("/api/calc/swp")
    def api_swp(p: SwpPayload):
        try:
            return core.swp(p.corpus, p.monthly, p.annual_pct, p.years)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    class LicPayload(BaseModel):
        annual_premium: float
        premium_years: float
        term_years: float
        maturity_amount: float

    @app.post("/api/calc/lic")
    def api_lic(p: LicPayload):
        try:
            return core.lic(p.annual_premium, p.premium_years, p.term_years, p.maturity_amount)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/market/health")
    def api_market_health():
        return market.get_provider_health()

    @app.get("/api/market/quote")
    def api_market_quote(kind: str = "stock", symbol: str = "", mode: str = "live"):
        return market.get_live_quote(kind, symbol, mode=mode)

    @app.get("/api/market/forecast")
    def api_market_forecast(symbol: str = ""):
        return core.market_forecast(symbol)

    @app.get("/api/market/ipos")
    def api_ipos(mode: str = "live"):
        return market.get_ipos(mode=mode)

    class InvestPayload(BaseModel):
        symbol: str = "AMZN"
        horizon_days: int = 90
        capital: float = 100000.0
        mode: Optional[str] = "live"

    @app.api_route("/api/market/invest", methods=["GET", "POST"])
    def api_market_invest(symbol: str = "AMZN", horizon_days: int = 90, capital: float = 100000.0, mode: str = "live", p: Optional[InvestPayload] = None):
        if p:
            return market.analyze_investment(p.symbol, p.horizon_days, p.capital, mode=p.mode or "live")
        return market.analyze_investment(symbol, horizon_days, capital, mode=mode)

    @app.get("/api/market/commodity")
    def api_market_commodity(name: str = "gold", mode: str = "live"):
        return market.get_live_commodity(name, mode=mode)

    @app.get("/api/market/alpaca/account")
    def api_alpaca_account():
        return market.get_alpaca_account()

    @app.get("/api/market/alpaca/positions")
    def api_alpaca_positions():
        return market.get_alpaca_positions()

    class AlpacaOrderPayload(BaseModel):
        symbol: str = Field(..., pattern=r"^[A-Za-z0-9.]{1,10}$")
        qty: int = Field(..., gt=0, description="Quantity must be strictly positive integer (> 0)")
        side: str = Field(..., pattern=r"^(buy|sell|BUY|SELL)$")
        order_type: Optional[str] = "market"
        time_in_force: Optional[str] = "day"
        client_order_id: Optional[str] = None

    @app.post("/api/market/alpaca/order")
    def api_alpaca_order(p: AlpacaOrderPayload):
        if p.qty <= 0:
            raise HTTPException(status_code=400, detail="Order quantity must be strictly greater than 0")
        res = market.place_alpaca_order(
            symbol=p.symbol,
            qty=p.qty,
            side=p.side.lower(),
            order_type=p.order_type or "market",
            time_in_force=p.time_in_force or "day",
            client_order_id=p.client_order_id
        )
        if res.get("status") == "error" and res.get("feed_status") == "validation_failed":
            raise HTTPException(status_code=400, detail=res.get("error"))
        return res

    # OHLCV Candlestick Data
    @app.get("/api/market/ohlcv")
    def api_ohlcv(symbol: str = "AMZN", interval: str = "1day", outputsize: int = 45, mode: str = "live"):
        return market.get_ohlcv(symbol, interval, outputsize, mode=mode)

    # Crypto Prices
    @app.get("/api/market/crypto")
    def api_crypto(symbol: str = "BTC", mode: str = "live"):
        return market.get_crypto_price(symbol, mode=mode)

    # Forex
    @app.get("/api/market/forex")
    def api_forex(from_currency: str = "USD", to_currency: str = "INR", mode: str = "live"):
        return market.get_forex(from_currency, to_currency, mode=mode)

    # India Indices
    @app.get("/api/market/india")
    def api_india_index(index: str = "NIFTY 50", mode: str = "live"):
        return market.get_india_index(index, mode=mode)

    # Natural Gas
    @app.get("/api/market/naturalgas")
    @app.get("/api/market/naturalgas&mode=live")
    def api_natural_gas(mode: str = "live"):
        return market.get_natural_gas(mode=mode)

    # Company Profile & Fundamentals
    @app.get("/api/market/profile")
    def api_company_profile(symbol: str = "AAPL", mode: str = "live"):
        return market.get_company_profile(symbol, mode=mode)

    # Company News
    @app.get("/api/market/news")
    def api_company_news(symbol: str = "AAPL", count: int = 5, mode: str = "live"):
        return market.get_company_news(symbol, count, mode=mode)

    # Company Metrics (P/E, ROE, Beta, etc.)
    @app.get("/api/market/metrics")
    def api_stock_metrics(symbol: str = "AAPL", mode: str = "live"):
        return market.get_stock_metrics(symbol, mode=mode)

    # Market Overview (Global Snapshot)
    @app.get("/api/market/overview")
    def api_market_overview(mode: str = "live"):
        return market.get_market_overview(mode=mode)

    # Web Search (DuckDuckGo)
    @app.get("/api/search")
    def api_web_search(q: str = ""):
        return market.web_search(q)

    # Watchlist Prices (batch)
    @app.api_route("/api/market/watchlist-prices", methods=["GET", "POST"])
    async def api_watchlist_prices(request: Request):
        if request.method == "GET":
            syms_str = request.query_params.get("symbols", "AAPL,MSFT,NVDA,AMZN,GOOGL")
            syms = [s.strip().upper() for s in syms_str.split(",") if s.strip()]
            mode = request.query_params.get("mode", "live")
            return market.get_watchlist_prices(syms, mode=mode)
        try:
            body = await request.json()
        except Exception:
            body = {}
        syms = body.get("symbols") or ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL"]
        mode = body.get("mode", "live")
        return market.get_watchlist_prices(syms, mode=mode)

    # Paper Trading (oracle_ai paper account summary)
    @app.api_route("/api/market/paper-trade", methods=["GET", "POST"])
    async def api_paper_trade(request: Request):
        if request.method == "GET":
            import bot as _bot_mod
            return await asyncio.to_thread(_bot_mod.account_summary)
        try:
            body = await request.json()
        except Exception:
            body = {}
        action = body.get("action", "summary")
        if action == "summary":
            import bot as _bot_mod
            return await asyncio.to_thread(_bot_mod.account_summary)
        symbol = body.get("symbol", "")
        shares = int(body.get("shares", 0))
        price = float(body.get("price", 0.0))
        return paper_trader.execute_trade(symbol, action, shares, price)

    # Watchlist (SQLite-backed)
    class WatchlistAddPayload(BaseModel):
        symbol: str
        note: Optional[str] = ""

    @app.post("/api/watchlist/add")
    def api_watchlist_add(p: WatchlistAddPayload, user=Depends(require_user)):
        return core.add_to_watchlist(user, p.symbol, p.note or "")

    @app.get("/api/watchlist")
    def api_watchlist_get(user=Depends(require_user)):
        return core.get_watchlist(user)

    @app.delete("/api/watchlist/{symbol}")
    def api_watchlist_remove(symbol: str, user=Depends(require_user)):
        return core.remove_from_watchlist(user, symbol)

    # Alert management (SQLite-backed)
    class AlertPayload(BaseModel):
        symbol: str
        condition: str = "above"   # above | below
        threshold: float
        note: Optional[str] = ""

    @app.post("/api/alerts/add")
    def api_alert_add(p: AlertPayload, user=Depends(require_user)):
        return core.add_alert(user, p.symbol, p.condition, p.threshold, p.note or "")

    @app.get("/api/alerts")
    def api_alerts_list(user=Depends(require_user)):
        return core.list_alerts(user)

    @app.delete("/api/alerts/{alert_id}")
    def api_alert_delete(alert_id: int, user=Depends(require_user)):
        return core.delete_alert(user, alert_id)

    # WebSocket for real-time live market & telemetry streaming with subscription support
    from fastapi import WebSocket, WebSocketDisconnect
    import asyncio

    @app.websocket("/ws/telemetry")
    async def ws_telemetry(websocket: WebSocket):
        await websocket.accept()
        active_symbol = "AMZN"

        async def receiver():
            nonlocal active_symbol
            try:
                while True:
                    msg = await websocket.receive_json()
                    action = msg.get("action")
                    if action == "subscribe" and msg.get("symbol"):
                        new_sym = str(msg["symbol"]).upper().strip()
                        if new_sym:
                            active_symbol = new_sym
                            quote = await asyncio.to_thread(market.get_live_stock, active_symbol)
                            await websocket.send_json({
                                "type": "symbol_quote",
                                "requested_symbol": active_symbol,
                                "data": quote
                            })
                    elif action == "unsubscribe":
                        pass
            except (WebSocketDisconnect, Exception):
                pass

        async def sender():
            try:
                while True:
                    overview = await asyncio.to_thread(market.get_market_overview)
                    await websocket.send_json({
                        "type": "market_tick",
                        "timestamp": time.time(),
                        "data": overview
                    })
                    if active_symbol:
                        sym_quote = await asyncio.to_thread(market.get_live_stock, active_symbol)
                        await websocket.send_json({
                            "type": "symbol_quote",
                            "requested_symbol": active_symbol,
                            "data": sym_quote
                        })
                    await asyncio.sleep(15)
            except (WebSocketDisconnect, Exception):
                pass

        try:
            await asyncio.gather(receiver(), sender())
        except Exception:
            pass

    # ==========================================
    # FINLLM QUANT & DECISION INTELLIGENCE ROUTES
    # ==========================================
    @app.get("/api/finllm/status")
    def api_finllm_status():
        import finllm_engine
        return finllm_engine.get_model_status()

    @app.get("/api/finllm/signal")
    def api_finllm_signal(symbol: str = "AMZN", mode: str = "live"):
        import finllm_engine
        return finllm_engine.predict_signal(symbol, mode=mode)

    class FinLLMSignalPayload(BaseModel):
        symbol: str = "AMZN"
        mode: Optional[str] = "live"

    @app.post("/api/finllm/signal")
    def api_finllm_signal_post(p: FinLLMSignalPayload):
        import finllm_engine
        return finllm_engine.predict_signal(p.symbol, mode=p.mode or "live")

    @app.get("/api/finllm/deeplob")
    def api_finllm_deeplob(symbol: str = "AMZN"):
        import finllm_engine
        return finllm_engine.run_deeplob_signal(symbol)

    class FinLLMCalcPayload(BaseModel):
        type: str
        params: dict

    @app.post("/api/finllm/calc")
    def api_finllm_calc(p: FinLLMCalcPayload):
        import finllm_engine
        return finllm_engine.calculate_ca_banking(p.type, p.params)

    class FinLLMChatPayload(BaseModel):
        message: str

    @app.post("/api/finllm/chat")
    def api_finllm_chat(p: FinLLMChatPayload, user=Depends(get_current_user)):
        import finllm_engine
        u_name = user["username"] if user else "Guest Investor"
        return finllm_engine.run_finllm_agent(p.message, user_name=u_name)

    @app.get("/api/cricket")
    def api_cricket():
        return core.cricket()

    class CricketSimPayload(BaseModel):
        team1: str = "India"
        team2: str = "Australia"
        format: str = "T20"
        target: float = 180
        current_runs: float = 110
        wickets_down: int = 3
        overs_completed: float = 13.2

    @app.post("/api/cricket/simulate")
    def api_cricket_simulate(p: CricketSimPayload):
        return market.cricket_match_simulator(p.team1, p.team2, p.format, p.target, p.current_runs, p.wickets_down, p.overs_completed)

    @app.get("/api/inventory")
    def api_inventory():
        return core.get_inventory_analysis()

    @app.get("/api/billing/plans")
    def api_billing_plans():
        return billing.get_plans()

    class SubscribePayload(BaseModel):
        plan_id: str

    @app.post("/api/billing/subscribe")
    def api_subscribe(p: SubscribePayload, user=Depends(require_user)):
        return billing.generate_invoice(user.get("email", "client@corp.in"), p.plan_id, user["ws"])

    @app.get("/api/automations/queue")
    def api_automations_queue():
        return automations.automations.list_queue()

    @app.get("/api/automations/rules")
    def api_automations_rules():
        return automations.automations.list_rules()

    class ActionDecisionPayload(BaseModel):
        action_id: str
        decision: str

    @app.post("/api/automations/action")
    def api_automations_action(p: ActionDecisionPayload, user=Depends(require_user)):
        if p.decision == "approve":
            return automations.automations.approve_action(p.action_id, user["role"])
        return automations.automations.reject_action(p.action_id, user["role"])

    @app.get("/api/audit-trail")
    def api_audit(user=Depends(require_user)):
        return {"kind": "actual", "logs": core.get_audit_trail(user)}

    try:
        from oracle_wiring import build_bot_router
        import finllm_engine
        app.include_router(build_bot_router(
            app, market, core, get_current_user,
            signal_fn=finllm_engine.predict_signal,
            deeplob_fn=finllm_engine.run_deeplob_signal,
            place_order_fn=lambda rec: market.place_alpaca_order(rec.get("symbol", "AMZN"), rec.get("qty", 1), rec.get("side", "buy"))
        ))
    except Exception as _bot_err:
        print(f"[ORACLE] Bot router optional mount note: {_bot_err}")

    # Mount oracle_ai market-intelligence backend
    try:
        import sys
        _oracle_ai_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oracle_ai")
        if _oracle_ai_dir not in sys.path:
            sys.path.insert(0, _oracle_ai_dir)

        from oracle_ai import routes as oracle_ai_routes
        app.include_router(oracle_ai_routes.router)
    except Exception as _ai_err:
        print(f"[ORACLE] Oracle AI router optional mount note: {_ai_err}")

    _stop_oracle_bot = asyncio.Event()

    if not os.environ.get("VERCEL"):
        @app.on_event("startup")
        async def _start_oracle_bot():
            try:
                from oracle_ai import bot as oracle_ai_bot
                asyncio.create_task(oracle_ai_bot.run_forever(_stop_oracle_bot))
            except Exception as e:
                print(f"[ORACLE] Bot task startup note: {e}")
            try:
                from oracle_ai.smartapi_client import stream_manager
                stream_manager.start()
            except Exception as e:
                pass

        @app.on_event("shutdown")
        async def _stop_oracle_bot_task():
            _stop_oracle_bot.set()
            try:
                from oracle_ai.smartapi_client import stream_manager
                stream_manager.stop()
            except Exception:
                pass

    class ChatPayload(BaseModel):
        message: str

    @app.post("/api/chat_legacy")
    def api_chat_legacy(p: ChatPayload, user=Depends(get_current_user)):
        d_ctx = core.workspace_dashboard(user) if user else core.dashboard(core.demo_df(), "demo")
        return {"reply": core.chat(p.message, d_ctx)}

    # Mount static assets
    @app.get("/")
    def serve_index():
        idx = os.path.join(STATIC, "index.html")
        if not os.path.exists(idx):
            idx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
        return FileResponse(idx, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})

    if os.path.exists(STATIC):
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

except ImportError:
    app = None
except Exception as _boot_err:
    import traceback as _tb
    print(f"[SERVER BOOT ERROR] FastAPI initialization warning: {_boot_err}")
    _tb.print_exc()
    if 'app' not in locals() or app is None:
        try:
            from fastapi import FastAPI
            app = FastAPI(title="ORACLE Fallback")
        except Exception:
            app = None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"ORACLE Intelligence Server running on http://localhost:{port}")
    try:
        import uvicorn
        if app:
            uvicorn.run("server:app", host="127.0.0.1", port=port, log_level="info")
        else:
            ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    except Exception:
        ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
