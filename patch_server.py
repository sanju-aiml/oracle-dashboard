import os

with open('C:/Users/BOTTA THARUN/Videos/oracle/oracle/server.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('\r\n', '\n')

old_pt = """    # Paper Trading
    @app.api_route("/api/market/paper-trade", methods=["GET", "POST"])
    async def api_paper_trade(request: Request):
        action = "summary"
        symbol = ""
        shares = 0
        price = 0.0
        if request.method == "POST":
            try:
                body = await request.json()
                action = body.get("action", "summary")
                symbol = body.get("symbol", "")
                shares = int(body.get("shares", 0))
                price = float(body.get("price", 0.0))
            except Exception:
                pass
        else:
            action = request.query_params.get("action", "summary")
            symbol = request.query_params.get("symbol", "")
            shares = int(request.query_params.get("shares", 0))
            price = float(request.query_params.get("price", 0.0))

        if action == "summary":
            return paper_trader.get_summary()
        return paper_trader.execute_trade(symbol, action, shares, price)"""

new_pt = """    # Paper Trading (oracle_ai paper account summary)
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
        return paper_trader.execute_trade(symbol, action, shares, price)"""

assert old_pt in content, "Could not find old_pt in server.py"
content = content.replace(old_pt, new_pt, 1)

mount_target = """        place_order_fn=lambda rec: market.place_alpaca_order(rec.get("symbol", "AMZN"), rec.get("qty", 1), rec.get("side", "buy"))
    ))"""

mount_replacement = """        place_order_fn=lambda rec: market.place_alpaca_order(rec.get("symbol", "AMZN"), rec.get("qty", 1), rec.get("side", "buy"))
    ))

    # Mount oracle_ai market-intelligence backend
    import sys
    _oracle_ai_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oracle_ai")
    if _oracle_ai_dir not in sys.path:
        sys.path.insert(0, _oracle_ai_dir)

    from oracle_ai import routes as oracle_ai_routes
    from oracle_ai import bot as oracle_ai_bot

    app.include_router(oracle_ai_routes.router)

    _stop_oracle_bot = asyncio.Event()

    @app.on_event("startup")
    async def _start_oracle_bot():
        asyncio.create_task(oracle_ai_bot.run_forever(_stop_oracle_bot))

    @app.on_event("shutdown")
    async def _stop_oracle_bot_task():
        _stop_oracle_bot.set()"""

assert mount_target in content, "Could not find mount_target in server.py"
content = content.replace(mount_target, mount_replacement, 1)

with open('C:/Users/BOTTA THARUN/Videos/oracle/oracle/server.py', 'w', encoding='utf-8') as f:
    f.write(content.replace('\n', '\r\n'))

print("Successfully updated server.py")
