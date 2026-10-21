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
core.migrate()
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
        self.end_headers()
        self.wfile.write(b)
        
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
                    
            if r == "market/quote":
                return self.send(200, market.get_live_quote(q.get("kind", "stock"), q.get("symbol", "")))
            if r == "market/forecast":
                return self.send(200, core.market_forecast(q.get("symbol", "")))
            if r == "market/ipos":
                return self.send(200, market.get_ipos())
            if r == "market/paper-trade":
                act = body.get("action", "summary")
                if act == "summary":
                    return self.send(200, paper_trader.get_summary())
                return self.send(200, paper_trader.execute_trade(body.get("symbol", ""), act, body.get("shares", 0), float(body.get("price", 0))))
                
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

    @app.get("/api/market/quote")
    def api_market_quote(kind: str = "stock", symbol: str = ""):
        return market.get_live_quote(kind, symbol)

    @app.get("/api/market/forecast")
    def api_market_forecast(symbol: str = ""):
        return core.market_forecast(symbol)

    @app.get("/api/market/ipos")
    def api_ipos():
        return market.get_ipos()

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

    class ChatPayload(BaseModel):
        message: str

    @app.post("/api/chat")
    def api_chat(p: ChatPayload, user=Depends(get_current_user)):
        d_ctx = core.workspace_dashboard(user) if user else core.dashboard(core.demo_df(), "demo")
        return {"reply": core.chat(p.message, d_ctx)}

    # Mount static assets
    if os.path.exists(STATIC):
        @app.get("/")
        def serve_index():
            return FileResponse(os.path.join(STATIC, "index.html"))

        app.mount("/static", StaticFiles(directory=STATIC), name="static")

except ImportError:
    app = None

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"ORACLE Intelligence Server running on http://localhost:{port}")
    try:
        import uvicorn
        if app:
            uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
        else:
            ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
    except Exception:
        ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
