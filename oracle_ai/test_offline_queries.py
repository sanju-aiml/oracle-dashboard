import sys
sys.path.insert(0, 'C:/Users/BOTTA THARUN/Videos/oracle/oracle/oracle_ai')
import requests
import answer as answer_mod

# Simulate offline (unplugged internet)
def _offline_get(*args, **kwargs):
    raise requests.exceptions.ConnectionError("Simulated offline: network unreachable")

requests.get = _offline_get
requests.Session.get = _offline_get

queries = ["bitcoin future", "gold", "crude oil", "natural gas", "nifty", "RELIANCE.NS"]
for q in queries:
    print(f"\n==================== OFFLINE QUERY: {q} ====================")
    try:
        res = answer_mod.answer(q)
        print(res["answer"])
    except Exception as e:
        print(f"Error answering {q}: {e}")
