"""News ingestion with strict timestamps (needed for look-ahead-safe training)."""
from __future__ import annotations
import pandas as pd

FEEDS = {
    "economic_times_markets": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "moneycontrol": "https://www.moneycontrol.com/rss/marketreports.xml",
    "livemint_markets": "https://www.livemint.com/rss/markets",
    "business_standard": "https://www.business-standard.com/rss/markets-106.rss",
    "rbi_press": "https://www.rbi.org.in/pressreleases_rss.xml",
    "sebi": "https://www.sebi.gov.in/sebirss.xml",
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "oilprice": "https://oilprice.com/rss/main",
}

def fetch_news(feeds: dict[str, str] | None = None) -> pd.DataFrame:
    import feedparser
    rows = []
    for name, url in (feeds or FEEDS).items():
        try:
            for e in feedparser.parse(url).entries:
                ts = pd.to_datetime(e.get("published", None), utc=True, errors="coerce")
                if pd.isna(ts):
                    continue
                rows.append({"ts": ts.tz_localize(None), "source": name, "title": e.get("title", ""),
                             "summary": e.get("summary", ""), "link": e.get("link", "")})
        except Exception as ex:
            print(f"[warn] {name}: {ex}")
    return pd.DataFrame(rows).drop_duplicates("link").sort_values("ts").reset_index(drop=True)
