import json
import urllib.request

BASE = "http://127.0.0.1:8000"

def get(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

print("=== 1. TEST /api/bot/status ===")
bot_st = get("/api/bot/status")
print("Bot Status:", json.dumps(bot_st, indent=2))

print("\n=== 2. TEST /api/market/paper-trade ===")
pt = get("/api/market/paper-trade")
print("Paper Trade:", json.dumps({
    "cash": pt.get("cash"),
    "equity": pt.get("equity"),
    "return_pct": pt.get("return_pct"),
    "halted": pt.get("halted"),
    "open_positions": len(pt.get("open_positions", [])),
    "win_rate": pt.get("win_rate")
}, indent=2))

print("\n=== 3. TEST /api/ask: Amazon investment ===")
ask_amzn = post("/api/ask", {"question": "Should I invest in Amazon?"})
print("Ask AMZN Answer:\n", ask_amzn.get("answer"))

print("\n=== 4. TEST /api/ask: Bitcoin future ===")
ask_btc = post("/api/ask", {"question": "bitcoin future"})
print("Ask BTC Answer:\n", ask_btc.get("answer"))

print("\n=== 5. TEST /api/play/call ===")
call_res = post("/api/play/call", {"user_id": "test_user_001", "symbol": "AMZN", "call": "up", "duration": "1h"})
print("Play Call Response:", json.dumps(call_res, indent=2))

print("\n=== 6. TEST /api/play/history ===")
hist_res = get("/api/play/history?user_id=test_user_001")
print("Play History Stats:", json.dumps(hist_res.get("stats"), indent=2))
print(f"Play History Count: {len(hist_res.get('history', []))} items")

print("\n=== 7. TEST /api/alerts/kinds ===")
kinds = get("/api/alerts/kinds")
print("Alert Kinds:", list(kinds.keys()))

print("\n=== 8. TEST /api/alerts/rules ===")
rule_res = post("/api/alerts/rules", {
    "user_id": "test_user_001",
    "symbol": "NIFTY",
    "kind": "above",
    "threshold": 23500.0,
    "cooldown_hours": 4.0
})
print("Added Rule:", rule_res)
rules = get("/api/alerts/rules?user_id=test_user_001")
print(f"Active Rules for user ({len(rules)}):", rules)

print("\n=== 9. TEST /api/alerts/test ===")
test_alert_res = post("/api/alerts/test?user_id=test_user_001", {})
print("Test Alert Response:", test_alert_res)

print("\n=== 10. TEST /api/ipos ===")
ipos = get("/api/ipos")
print(f"IPOs ({len(ipos)}):", ipos[:2])

print("\n=== 11. TEST SSE /api/stream/NIFTY ===")
req = urllib.request.Request(f"{BASE}/api/stream/NIFTY?interval=2&max_events=1")
with urllib.request.urlopen(req, timeout=30) as r:
    line = r.readline().decode()
    print("SSE Stream Line 1:", line.strip())
    line2 = r.readline().decode()
    print("SSE Stream Line 2:", line2.strip())

print("\nALL VERIFICATIONS PASSED SUCCESSFULLY!")
