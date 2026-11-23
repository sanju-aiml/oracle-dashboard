"""ORACLE AI configuration. Everything is overridable with environment variables."""
import os

BASE = os.path.dirname(os.path.abspath(__file__))
_odb = os.getenv("ORACLE_DB")
_is_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

import tempfile

if os.getenv("ORACLE_AI_DB"):
    DB_PATH = os.getenv("ORACLE_AI_DB")
elif _odb and os.path.basename(_odb).lower() != "oracle.db":
    DB_PATH = _odb
elif _is_serverless:
    DB_PATH = os.path.join(tempfile.gettempdir(), "oracle_data.db")
else:
    DB_PATH = os.path.join(BASE, "data", "oracle_data.db")

MODEL_DIR = os.getenv("ORACLE_MODELS", os.path.join(BASE, "models"))
UPLOAD_DIR = os.getenv("ORACLE_UPLOADS", os.path.join(tempfile.gettempdir(), "uploads") if _is_serverless else os.path.join(BASE, "uploads"))
GATE_LOG = os.getenv("ORACLE_GATE_LOG", os.path.join(tempfile.gettempdir(), "gate_log.jsonl") if _is_serverless else os.path.join(BASE, "gate_log.jsonl"))

for _d in (os.path.dirname(DB_PATH), MODEL_DIR, UPLOAD_DIR):
    if _d:
        try:
            os.makedirs(_d, exist_ok=True)
        except OSError:
            pass

# ---- keys / switches -------------------------------------------------------
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "")          # optional, free key from finnhub.io
ALLOW_SCRAPING = os.getenv("ALLOW_SCRAPING", "1") == "1"   # web backup (obeys robots.txt)
ADMIN_TOKEN = os.getenv("ORACLE_ADMIN_TOKEN", "")   # protects bot start/stop/train endpoints
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8"))
USER_AGENT = os.getenv("ORACLE_UA", "OracleAI/1.0 (+contact: set ORACLE_UA)")

# ---- data freshness --------------------------------------------------------
QUOTE_FRESH_SEC = 60            # reuse a stored quote younger than this
SUSPICIOUS_JUMP = 0.5           # reject a quote that differs >50% from last known price
SOURCE_DISAGREE = 0.02          # warn when two sources differ by more than 2%

INTERVAL_SEC = {"1h": 3600, "1d": 86400}

# ---- training gate ---------------------------------------------------------
HORIZONS = (1, 5)               # forecast horizons, in candles (days for 1d)
MIN_BARS = 400                  # fewer closed candles than this => not trained
GATE_ALPHA = 0.02               # holdout accuracy must beat the majority baseline at this p-value
GATE_MIN_AUC = 0.52
GATE_MIN_OOS = 200
HOLDOUT_FRAC = 0.20
CONFIGS = [
    dict(depth=2, lr=0.05, iters=120),
    dict(depth=3, lr=0.05, iters=150),
    dict(depth=3, lr=0.03, iters=250),
]
PROB_CLIP = (0.35, 0.65)        # the model is never allowed to sound more sure than 65%

# ---- paper bot -------------------------------------------------------------
PAPER_START_CASH = float(os.getenv("PAPER_START", "1000000"))
BOT_POLL_SEC = int(os.getenv("BOT_POLL_SEC", "60"))
BOT_REFRESH_SEC = int(os.getenv("BOT_REFRESH_SEC", "900"))
RISK_PER_TRADE = 0.01           # risk 1% of equity per trade
MAX_NOTIONAL_FRAC = 0.10        # a position is never bigger than 10% of equity
MAX_OPEN_POSITIONS = 5
MAX_DRAWDOWN = 0.10             # halt the bot at -10% from peak equity
ENTRY_EDGE = 0.04               # trade only when |p_up - 0.5| >= 4 points
STOP_ATR = 2.0
TARGET_ATR = 3.0
COST_PER_SIDE = {"crypto": 0.001, "stock": 0.0005, "commodity": 0.0005,
                 "index": 0.0005, "forex": 0.0002}

# user "play" calls (press UP / DOWN)
PLAY_DURATIONS = {"5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
PLAY_LATE_TOLERANCE = 600       # resolve only if we are within 10 min of the due time

# ---- assets ----------------------------------------------------------------
# yf = Yahoo ticker, binance = Binance pair, cg = CoinGecko id, stooq = Stooq code,
# fh = Finnhub symbol (US stocks), gf = Google Finance "TICKER:EXCHANGE"
ASSETS = {
    "BTC": dict(name="Bitcoin", cls="crypto", aliases=["bitcoin", "btc"], yf="BTC-USD", binance="BTCUSDT", cg="bitcoin", gf="BTC-USD"),
    "ETH": dict(name="Ethereum", cls="crypto", aliases=["ethereum", "ether", "eth"], yf="ETH-USD", binance="ETHUSDT", cg="ethereum", gf="ETH-USD"),
    "SOL": dict(name="Solana", cls="crypto", aliases=["solana", "sol"], yf="SOL-USD", binance="SOLUSDT", cg="solana"),
    "BNB": dict(name="BNB", cls="crypto", aliases=["bnb", "binance coin"], yf="BNB-USD", binance="BNBUSDT", cg="binancecoin"),
    "XRP": dict(name="XRP", cls="crypto", aliases=["xrp", "ripple"], yf="XRP-USD", binance="XRPUSDT", cg="ripple"),
    "DOGE": dict(name="Dogecoin", cls="crypto", aliases=["dogecoin", "doge"], yf="DOGE-USD", binance="DOGEUSDT", cg="dogecoin"),
    "XAU": dict(name="Gold", cls="commodity", aliases=["gold", "xau", "sona"], yf="GC=F", stooq="xauusd", gf="GCW00:COMEX"),
    "XAG": dict(name="Silver", cls="commodity", aliases=["silver", "xag"], yf="SI=F", stooq="xagusd"),
    "WTI": dict(name="Crude Oil (WTI)", cls="commodity", aliases=["crude oil", "wti", "oil", "crude"], yf="CL=F", stooq="cl.f"),
    "BRENT": dict(name="Brent Crude", cls="commodity", aliases=["brent"], yf="BZ=F"),
    "NG": dict(name="Natural Gas", cls="commodity", aliases=["natural gas", "natgas", "gas"], yf="NG=F", stooq="ng.f"),
    "AAPL": dict(name="Apple", cls="stock", aliases=["apple", "aapl"], yf="AAPL", stooq="aapl.us", fh="AAPL", gf="AAPL:NASDAQ"),
    "AMZN": dict(name="Amazon", cls="stock", aliases=["amazon", "amzn"], yf="AMZN", stooq="amzn.us", fh="AMZN", gf="AMZN:NASDAQ"),
    "NVDA": dict(name="Nvidia", cls="stock", aliases=["nvidia", "nvda"], yf="NVDA", stooq="nvda.us", fh="NVDA", gf="NVDA:NASDAQ"),
    "MSFT": dict(name="Microsoft", cls="stock", aliases=["microsoft", "msft"], yf="MSFT", stooq="msft.us", fh="MSFT", gf="MSFT:NASDAQ"),
    "TSLA": dict(name="Tesla", cls="stock", aliases=["tesla", "tsla"], yf="TSLA", stooq="tsla.us", fh="TSLA", gf="TSLA:NASDAQ"),
    "GOOGL": dict(name="Alphabet (Google)", cls="stock", aliases=["google", "alphabet", "googl"], yf="GOOGL", stooq="googl.us", fh="GOOGL", gf="GOOGL:NASDAQ"),
    "META": dict(name="Meta", cls="stock", aliases=["meta", "facebook"], yf="META", stooq="meta.us", fh="META", gf="META:NASDAQ"),
    "NIFTY": dict(name="Nifty 50", cls="index", aliases=["nifty", "nifty50", "nifty 50"], yf="^NSEI", nse_index="NIFTY 50"),
    "SENSEX": dict(name="BSE Sensex", cls="index", aliases=["sensex"], yf="^BSESN"),
    "RELIANCE": dict(name="Reliance Industries", cls="stock", aliases=["reliance"], yf="RELIANCE.NS", nse="RELIANCE"),
    "TCS": dict(name="TCS", cls="stock", aliases=["tcs"], yf="TCS.NS", nse="TCS"),
    "INFY": dict(name="Infosys", cls="stock", aliases=["infosys", "infy"], yf="INFY.NS", nse="INFY"),
    "HDFCBANK": dict(name="HDFC Bank", cls="stock", aliases=["hdfc bank", "hdfcbank"], yf="HDFCBANK.NS", nse="HDFCBANK"),
    "INDIAVIX": dict(name="India VIX", cls="index", aliases=["india vix", "vix"], yf="^INDIAVIX", nse_index="INDIA VIX"),
    "ICICIBANK": dict(name="ICICI Bank", cls="stock", aliases=["icici", "icicibank"], yf="ICICIBANK.NS", nse="ICICIBANK"),
    "SBIN": dict(name="State Bank of India", cls="stock", aliases=["sbi", "sbin"], yf="SBIN.NS", nse="SBIN"),
    "BHARTIARTL": dict(name="Bharti Airtel", cls="stock", aliases=["airtel", "bharti airtel"], yf="BHARTIARTL.NS", nse="BHARTIARTL"),
    "ITC": dict(name="ITC", cls="stock", aliases=["itc"], yf="ITC.NS", nse="ITC"),
    "KOTAKBANK": dict(name="Kotak Mahindra Bank", cls="stock", aliases=["kotak", "kotakbank"], yf="KOTAKBANK.NS", nse="KOTAKBANK"),
    "LT": dict(name="Larsen & Toubro", cls="stock", aliases=["l&t", "lt"], yf="LT.NS", nse="LT"),
    "USDINR": dict(name="USD/INR", cls="forex", aliases=["usd/inr", "usdinr", "dollar rupee", "rupee", "inr"], yf="INR=X", stooq="usdinr"),
}

BOT_SYMBOLS = [s for s in os.getenv("BOT_SYMBOLS", "").split(",") if s] or \
    [s for s, a in ASSETS.items() if a["cls"] != "forex"]

MAX_DYNAMIC_ASSETS = 200

# ---- notifications -----------------------------------------------------------
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_COOLDOWN = 6 * 3600
STRESS_NIFTY_DROP = -1.5        # % day move in Nifty that triggers a market-stress alert
STRESS_VIX_JUMP = 8.0           # % day jump in India VIX that triggers it
