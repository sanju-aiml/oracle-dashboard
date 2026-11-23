import sys
sys.path.insert(0, 'C:/Users/BOTTA THARUN/Videos/oracle/oracle/oracle_ai')
import market_data as md

for sym in ['RELIANCE', 'TCS', 'NIFTY']:
    print('Testing', sym)
    try:
        if sym == 'NIFTY':
            allowed = md._robots_allows('https://www.nseindia.com/api/allIndices')
            print('robots allowed:', allowed)
            val = md.q_nse_index('NIFTY 50')
            print('NSE index NIFTY 50:', val)
        else:
            url = 'https://www.nseindia.com/api/quote-equity?symbol=' + sym
            allowed = md._robots_allows(url)
            print('robots allowed:', allowed)
            val = md.q_nse_equity(sym)
            print('NSE equity', sym, ':', val)
    except Exception as e:
        print(sym, 'ERROR:', type(e), e)
