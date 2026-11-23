import sys
sys.path.insert(0, 'C:/Users/BOTTA THARUN/Videos/oracle/oracle/oracle_ai')
import market_data as md

test_syms = ['NIFTY', 'SENSEX', 'RELIANCE', 'TCS', 'HDFCBANK', 'BTC', 'ETH', 'AMZN', 'AAPL', 'XAU', 'XAG', 'WTI', 'NG', 'USDINR']
for s in test_syms:
    q = md.get_quote(s)
    print(f"{s:10s} -> price={q['price']:<12} source={q['source']:<18} status={q['status']}")
