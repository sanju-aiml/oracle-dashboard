import sys
sys.path.insert(0, 'C:/Users/BOTTA THARUN/Videos/oracle/oracle/oracle_ai')
import answer as answer_mod

queries = ["bitcoin future", "gold", "crude oil", "natural gas", "nifty", "RELIANCE.NS"]
for q in queries:
    print(f"\n==================== QUERY: {q} ====================")
    res = answer_mod.answer(q)
    print(res["answer"])
