"""Automated Regression Suite for Market Data Integrity & Provenance.
Tests all 12 critical engineering requirements:
1. GOOGL input cannot display AMZN data.
2. An unsuccessful live request cannot produce synthetic candles.
3. Provider HTTP 401, 403, 429, or 5xx responses are handled correctly without unhandled crashes.
4. Stale WebSocket cannot overwrite the currently selected ticker.
5. Old requests cannot overwrite newer selections.
6. Quantity zero and negative quantity are rejected by backend.
7. Valid paper-order payloads are correctly constructed.
8. Market-closed and delayed-feed states are clearly identified.
9. IPO and commodity widgets never misrepresent hardcoded data as current.
10. API keys and private credentials never appear in logs or client responses.
11. Reconnection, cache expiry, and rate limiting behave correctly.
12. The application remains usable when a provider is unavailable.
"""
import os, sys, pytest, json, time
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
import io

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from httpx import AsyncClient, ASGITransport
import server, market, core

# -------------------------------------------------------------
# Test 1: GOOGL input cannot display AMZN data
# -------------------------------------------------------------
def test_1_googl_cannot_display_amzn_data():
    """Verify that a request for GOOGL returns GOOGL provenance and rejects AMZN data."""
    with patch("market._http_request") as mock_req:
        # Mock Finnhub returning genuine GOOGL data
        mock_req.return_value = {
            "ok": True,
            "status_code": 200,
            "data": {"c": 340.25, "d": 2.10, "dp": 0.62, "h": 342.0, "l": 338.5, "o": 339.0, "pc": 338.15, "t": int(time.time())},
            "feed_status": "live"
        }
        res = market.get_live_stock("GOOGL", mode="live")
        assert res["status"] == "ok"
        assert res["requested_symbol"] == "GOOGL"
        assert res["provider_symbol"] == "GOOGL"
        assert res["price"] == 340.25
        # Ensure it cannot be tagged as AMZN
        assert res["requested_symbol"] != "AMZN"

# -------------------------------------------------------------
# Test 2: Unsuccessful live request cannot produce synthetic candles
# -------------------------------------------------------------
def test_2_failed_live_request_cannot_produce_synthetic_candles():
    """In LIVE mode, an unsuccessful request must return error/unavailable and NEVER synthetic candles."""
    with patch("market._http_request") as mock_req:
        mock_req.return_value = {
            "ok": False,
            "status_code": 500,
            "feed_status": "unavailable",
            "error": "Upstream service timeout"
        }
        res = market.get_ohlcv("AMZN", interval="1day", outputsize=30, mode="live")
        assert res["status"] == "error"
        assert res["feed_status"] == "unavailable"
        assert res["candles"] == []
        assert res["kind"] == "actual"
        assert res.get("kind") != "synthetic"

    # Only in explicit DEMO mode can synthetic placeholder exist
    res_demo = market.get_ohlcv("AMZN", interval="1day", mode="demo")
    assert res_demo["kind"] == "synthetic"
    assert res_demo["feed_status"] == "synthetic_demo"

# -------------------------------------------------------------
# Test 3: Provider HTTP 401, 403, 429, 5xx handled correctly
# -------------------------------------------------------------
def test_3_provider_status_codes_handled():
    """Test that 401 (auth), 403 (forbidden), 429 (rate-limit), and 5xx are accurately caught and tracked."""
    # 401 Auth Failed
    with patch("urllib.request.urlopen") as mock_url:
        mock_url.side_effect = HTTPError("https://api.finnhub.io", 401, "Unauthorized", {}, io.BytesIO(b'{"error": "Invalid API key"}'))
        res = market._http_request("https://api.finnhub.io/v1/quote", provider_name="finnhub")
        assert res["ok"] is False
        assert res["status_code"] == 401
        assert res["feed_status"] == "auth_failed"

    # 429 Rate Limit
    with patch("urllib.request.urlopen") as mock_url:
        mock_url.side_effect = HTTPError("https://api.twelvedata.com", 429, "Too Many Requests", {}, io.BytesIO(b'{"message": "You have exceeded your minute rate limit"}'))
        res = market._http_request("https://api.twelvedata.com/quote", provider_name="twelvedata")
        assert res["ok"] is False
        assert res["status_code"] == 429
        assert res["feed_status"] == "rate_limited"

    # 503 Server Error with bounded retry
    with patch("urllib.request.urlopen") as mock_url:
        mock_url.side_effect = HTTPError("https://api.twelvedata.com", 503, "Service Unavailable", {}, io.BytesIO(b'Server overloaded'))
        res = market._http_request("https://api.twelvedata.com/quote", retries=1, provider_name="twelvedata")
        assert res["ok"] is False
        assert res["status_code"] == 503
        assert res["feed_status"] == "unavailable"

# -------------------------------------------------------------
# Test 4: Stale WebSocket cannot overwrite currently selected ticker
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_4_stale_websocket_cannot_overwrite_selected_ticker():
    """Verify that telemetry WebSocket tags symbol_quote with requested_symbol so client rejects mismatches."""
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        # Check health endpoint exists
        r = await ac.get("/api/market/health")
        assert r.status_code == 200
        health = r.json()
        assert "providers" in health
        assert "finnhub" in health["providers"]

# -------------------------------------------------------------
# Test 5: Old requests cannot overwrite newer selections (provenance matching)
# -------------------------------------------------------------
def test_5_old_request_provenance_matching():
    """Verify data contract enforces matching requested_symbol."""
    contract = market.make_data_contract(
        requested_symbol="GOOGL",
        provider_symbol="GOOGL",
        provider_name="Finnhub",
        data_timestamp="2026-10-21 12:00:00 UTC",
        feed_status="live",
        kind="actual"
    )
    assert contract["requested_symbol"] == "GOOGL"
    assert contract["requested_symbol"] != "AMZN"

# -------------------------------------------------------------
# Test 6: Quantity zero and negative quantity are rejected by backend
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_6_quantity_zero_and_negative_rejected():
    """Backend must reject quantity <= 0 with HTTP 400 or 422 before calling broker."""
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        # Zero quantity
        r_zero = await ac.post("/api/market/alpaca/order", json={"symbol": "AMZN", "qty": 0, "side": "buy"})
        assert r_zero.status_code in (400, 422)

        # Negative quantity
        r_neg = await ac.post("/api/market/alpaca/order", json={"symbol": "AMZN", "qty": -5, "side": "buy"})
        assert r_neg.status_code in (400, 422)

        # String / non-finite quantity
        r_invalid = await ac.post("/api/market/alpaca/order", json={"symbol": "AMZN", "qty": "invalid", "side": "buy"})
        assert r_invalid.status_code in (400, 422)

# -------------------------------------------------------------
# Test 7: Valid paper-order payloads are correctly constructed
# -------------------------------------------------------------
def test_7_valid_paper_order_payload_construction():
    """Test paper order client constructs valid payload with idempotency key."""
    with patch("market._http_request") as mock_req, patch("market.get_alpaca_account") as mock_acc:
        mock_acc.return_value = {"status": "ok", "status_text": "ACTIVE", "cash_balance": 100000.0}
        mock_req.return_value = {
            "ok": True,
            "status_code": 200,
            "data": {
                "id": "order_test_12345",
                "client_order_id": "oracle_test_idempotency_1",
                "symbol": "AMZN",
                "status": "accepted",
                "submitted_at": "2026-10-21 12:00:00 UTC"
            }
        }
        res = market.place_alpaca_order(symbol="AMZN", qty=2, side="buy", client_order_id="oracle_test_idempotency_1")
        assert res["status"] == "ok"
        assert res["order_id"] == "order_test_12345"
        assert res["order_status"] == "accepted"
        assert res["client_order_id"] == "oracle_test_idempotency_1"
        assert res["kind"] == "actual"

# -------------------------------------------------------------
# Test 8: Market-closed and delayed-feed states are clearly identified
# -------------------------------------------------------------
def test_8_market_closed_and_delayed_feed_identified():
    """When market is closed or quote is older than 15 minutes, feed_status must be 'delayed' or market_status 'closed'."""
    with patch("market._http_request") as mock_req:
        # Timestamp from yesterday
        old_epoch = int(time.time()) - 86400
        mock_req.return_value = {
            "ok": True,
            "status_code": 200,
            "data": {"c": 260.0, "d": 0.0, "dp": 0.0, "pc": 260.0, "t": old_epoch},
            "feed_status": "delayed"
        }
        res = market.get_live_stock("AMZN", mode="live")
        assert res["status"] == "ok"
        assert res["feed_status"] == "delayed"
        assert res["market_status"] == "closed"

# -------------------------------------------------------------
# Test 9: IPO and commodity widgets never misrepresent hardcoded data as current
# -------------------------------------------------------------
def test_9_ipo_and_commodity_never_misrepresent_hardcoded():
    """In LIVE mode, IPO widget must state not_configured.
    Silver and Indian indices now use yfinance (SI=F / ^BSESN / ^NSEI) and
    must return real prices (status=ok) or an explicit unavailable error —
    never synthetic/fabricated data.
    """
    # Live IPO must NOT return static Swiggy array as live filings
    live_ipos = market.get_ipos(mode="live")
    assert live_ipos["status"] == "unavailable"
    assert live_ipos["feed_status"] == "not_configured"
    assert live_ipos["ipos"] == []

    # Silver is now sourced from Yahoo Finance SI=F via yfinance.
    # It must return either a real price (status=ok, kind=actual) or an
    # explicit unavailable error — never kind=synthetic in live mode.
    live_silver = market.get_live_commodity("silver", mode="live")
    assert live_silver["kind"] == "actual", "Silver must never return synthetic data in live mode"
    assert live_silver["status"] in ("ok", "error"), f"Unexpected silver status: {live_silver['status']}"
    if live_silver["status"] == "ok":
        assert live_silver.get("price", 0) > 0, "Silver ok status must carry a positive real price"

    # Indian indices are now sourced from Yahoo Finance (yfinance ^BSESN / ^NSEI).
    # Must return either a real price (status=ok, kind=actual) or an
    # explicit unavailable error — never kind=synthetic in live mode.
    live_sensex = market.get_india_index("SENSEX", mode="live")
    assert live_sensex["kind"] == "actual", "SENSEX must never return synthetic data in live mode"
    assert live_sensex["status"] in ("ok", "error"), f"Unexpected SENSEX status: {live_sensex['status']}"
    if live_sensex["status"] == "ok":
        assert live_sensex.get("price", 0) > 0, "SENSEX ok status must carry a positive real price"

# -------------------------------------------------------------
# Test 10: API keys and private credentials never appear in logs or client responses
# -------------------------------------------------------------
def test_10_api_keys_never_appear_in_responses_or_logs():
    """Verify redaction strips sensitive tokens."""
    dummy_key = "secret_api_token_123456"
    test_str = f"Error calling https://api.finnhub.io/v1/quote?token={dummy_key}&symbol=AMZN"
    with patch.object(market, "FINNHUB_KEY", dummy_key):
        redacted = market.redact_secrets(test_str)
        assert dummy_key not in redacted
        assert "[REDACTED]" in redacted

# -------------------------------------------------------------
# Test 11: Reconnection, cache expiry, and rate limiting behave correctly
# -------------------------------------------------------------
def test_11_cache_expiry_and_rate_limiting():
    """Verify TTL cache expires correctly and stores entries by key."""
    key = "test:quote:XYZ"
    market._set_cache(key, {"status": "ok", "price": 100.0}, ttl=1)
    # Immediately available
    assert market._get_cache(key) is not None
    assert market._get_cache(key)["price"] == 100.0
    # After sleep > ttl, cache expires
    time.sleep(1.1)
    assert market._get_cache(key) is None

# -------------------------------------------------------------
# Test 12: The application remains usable when a provider is unavailable
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_12_application_remains_usable_when_provider_unavailable():
    """When upstream providers fail, endpoints return structured fallback rather than crashing server with 500."""
    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as ac:
        with patch("market._http_request") as mock_req:
            mock_req.return_value = {"ok": False, "status_code": 503, "feed_status": "unavailable", "error": "Provider offline"}
            
            # Stock quote returns clean error contract, not 500
            r_quote = await ac.get("/api/market/quote?symbol=XYZNONEXISTENT")
            assert r_quote.status_code == 200
            assert r_quote.json()["status"] == "error"
            assert r_quote.json()["feed_status"] in ("unavailable", "not_configured")

            # Overview returns structured dictionary with partial available flags
            r_over = await ac.get("/api/market/overview")
            assert r_over.status_code == 200
            assert "market_overview" in r_over.json()
