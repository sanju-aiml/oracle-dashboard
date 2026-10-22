"""Tools the LLM may call. Numbers come from here (live data, calculators, signal model, RAG) — not from model memory."""
from __future__ import annotations
from typing import Callable
from ..data import calc

class Tools:
    def __init__(self, store=None, signal_fn: Callable | None = None):
        self.store, self.signal_fn = store, signal_fn
        self.registry: dict[str, Callable] = {
            "get_quote": self.get_quote, "get_history": self.get_history, "get_news": self.get_news,
            "signal": self.signal, "search_docs": self.search_docs,
            "gst": calc.gst, "emi": calc.emi, "sip_fv": calc.sip_fv, "compound": calc.compound,
            "tds_194c": calc.tds_194c, "hra_exemption": calc.hra_exemption, "tax_new_regime": calc.tax_new_regime,
        }

    def call(self, name: str, args: dict):
        if name not in self.registry:
            raise ValueError(f"unknown tool {name}")
        return self.registry[name](**args)

    def get_quote(self, symbol: str):
        from ..data.market import fetch_quote
        return fetch_quote(symbol)

    def get_history(self, symbol: str, days: int = 120):
        from ..data.market import fetch_history
        import pandas as pd
        d = fetch_history([symbol], start=(pd.Timestamp.today() - pd.Timedelta(days=days * 2)).strftime("%Y-%m-%d"))
        return d.tail(days)[["date", "close", "volume"]].astype({"date": str}).to_dict("records")

    def get_news(self, query: str = "", n: int = 8):
        from ..data.news import fetch_news
        df = fetch_news()
        if query:
            df = df[df["title"].str.contains(query, case=False, na=False)]
        return df.tail(n)[["ts", "source", "title", "link"]].astype({"ts": str}).to_dict("records")

    def signal(self, symbol: str):
        if not self.signal_fn:
            raise RuntimeError("signal model not loaded")
        return self.signal_fn(symbol)

    def search_docs(self, query: str, k: int = 4):
        return [{"source": d["source"], "text": d["text"][:600]} for d in self.store.search(query, k)] if self.store else []
