"""Run ONCE while online (then daily): downloads history into ORACLE's own database so that answers
and training never depend on a live API again.   python seed_history.py [SYMBOL ...]"""
import sys
import time

import config
import market_data as md


def main(symbols):
    for s in symbols:
        n, src = md.seed_history(s, "1d", 2000)
        q = md.get_quote(s)
        print(f"{s:9s} candles={n:5d} source={src or '-':14s} quote={q['price']} ({q['status']})")
        time.sleep(0.5)                       # be polite to the data providers


if __name__ == "__main__":
    main(sys.argv[1:] or list(config.ASSETS))
