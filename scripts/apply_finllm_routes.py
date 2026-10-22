import re

# 1. Update server.py
with open("server.py", "r", encoding="utf-8") as f:
    server_content = f.read()

finllm_fastapi_routes = '''    # ==========================================
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

'''

stdlib_routes = '''            if r == "finllm/status":
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
'''

if "/api/finllm/status" not in server_content:
    fastapi_target = '    @app.get("/api/cricket")'
    if fastapi_target in server_content:
        server_content = server_content.replace(fastapi_target, finllm_fastapi_routes + fastapi_target)
        print("[*] Injected FinLLM FastAPI routes")

    stdlib_target = '            if r == "cricket":'
    if stdlib_target in server_content:
        server_content = server_content.replace(stdlib_target, stdlib_routes + stdlib_target)
        print("[*] Injected FinLLM stdlib routes")

    with open("server.py", "w", encoding="utf-8") as f:
        f.write(server_content)
    print("[*] Saved updated server.py")
else:
    print("[*] FinLLM routes already present in server.py")

# 2. Update core.py to add CA calculators and FinLLM signal into chat()
with open("core.py", "r", encoding="utf-8") as f:
    core_content = f.read()

ca_calc_code = '''        if "gst" in m and len(n) >= 1:
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
                return f"Loan EMI Calculation: Principal ₹{p:,.2f} at {r}% for {y} years: Monthly EMI = ₹{res['emi']:,.2f}, Total Interest = ₹{res['total_interest']:,.2f}, Total Payment = ₹{res['total_payment']:,.2f}."
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
                res = finllm_engine.calculate_ca_banking("tax_new_regime", {"income": inc, "deductions": ded})["result"]
                return f"Income Tax (New Regime FY25-26): Gross Income ₹{inc:,.2f}, Standard Deduction ₹{ded:,.2f}, Taxable Income ₹{res['taxable_income']:,.2f}, Base Tax ₹{res['base_tax']:,.2f}, Rebate 87A: ₹{res['rebate_87a']:,.2f}, Cess (4%): ₹{res['cess']:,.2f}, Total Tax = ₹{res['total']:,.2f}."
            except Exception as e:
                return f"Tax calculation failed: {str(e)}"
'''

if 'import finllm_engine' not in core_content:
    # Insert right after `return f"Fixed Deposit: Principal ...\n`
    pattern = r'(return f"Fixed Deposit: Principal.*?\n)'
    match = re.search(pattern, core_content)
    if match:
        idx = match.end()
        core_content = core_content[:idx] + ca_calc_code + core_content[idx:]
        print("[*] Injected CA calculators into core.py chat()")

    with open("core.py", "w", encoding="utf-8") as f:
        f.write(core_content)
    print("[*] Saved updated core.py")
else:
    print("[*] finllm_engine already present in core.py")
