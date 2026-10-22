"""Realtime layer: keeps a rolling cache of quotes, crypto candles and news fresh, and exposes per-symbol signals.
python -m finllm.serve.live --interval 60   (run alongside the API)"""
from __future__ import annotations
import argparse, json, os, time
import pandas as pd

class LiveCache:
    def __init__(self, path="data/live_cache.json", symbols=None, fetch_quote=None, fetch_news=None):
        from ..data import market, news
        self.path = path
        self.symbols = symbols or ["^NSEI", "^BSESN", "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "GC=F", "CL=F", "BZ=F", "USDINR=X", "BTC-USD", "ETH-USD"]
        self.fetch_quote = fetch_quote or market.fetch_quote
        self.fetch_news = fetch_news or news.fetch_news
        self.state = {"quotes": {}, "news": [], "updated": None}

    def refresh(self):
        for s in self.symbols:
            try:
                self.state["quotes"][s] = self.fetch_quote(s)
            except Exception as e:
                self.state["quotes"].setdefault(s, {"error": str(e)})
        try:
            df = self.fetch_news().tail(50)
            self.state["news"] = [{"ts": str(r.ts), "source": r.source, "title": r.title, "link": r.link} for r in df.itertuples()]
        except Exception as e:
            self.state["news_error"] = str(e)
        self.state["updated"] = pd.Timestamp.now("UTC").isoformat()
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        json.dump(self.state, open(tmp, "w"), default=str, ensure_ascii=False)
        os.replace(tmp, self.path)                                 # atomic: readers never see a half-written file
        return self.state

    def stale(self, max_age_s=300) -> bool:
        u = self.state.get("updated")
        return u is None or (pd.Timestamp.now("UTC") - pd.Timestamp(u)).total_seconds() > max_age_s

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--interval", type=int, default=60)
    a = ap.parse_args(); c = LiveCache()
    while True:
        c.refresh(); print("refreshed", c.state["updated"], flush=True); time.sleep(a.interval)
