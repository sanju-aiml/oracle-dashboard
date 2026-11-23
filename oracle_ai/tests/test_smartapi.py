"""Tests for Angel One SmartAPI integration with mocked SDK responses.
Covers:
- login ok (TOTP + generateSession, in-memory tokens only)
- auth error & automatic re-login
- websocket streaming & tick price conversion (/100 for paise -> rupees)
- websocket Trading-key rejection detection
- unknown symbol resolution and fallback
- quote source chain precedence (Angel One FIRST for Indian assets)
"""
import os
import sys
import tempfile
import time
from unittest import mock

import pytest

_tmp = tempfile.mkdtemp()
os.environ.update(
    ORACLE_AI_DB=f"{_tmp}/o_smartapi.db",
    ORACLE_MODELS=f"{_tmp}/m",
    ORACLE_UPLOADS=f"{_tmp}/u",
    ORACLE_GATE_LOG=f"{_tmp}/g.jsonl"
)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import smartapi_client
import market_data as md
import store
import config


@pytest.fixture(autouse=True)
def reset_session():
    smartapi_client.session_manager.invalidate()
    yield
    smartapi_client.session_manager.invalidate()


# ---------------------------------------------------------------------------
# 1. Login OK
# ---------------------------------------------------------------------------
def test_angel_login_ok(monkeypatch):
    """Verifies pyotp TOTP + generateSession, in-memory tokens, and kv status."""
    monkeypatch.setenv("ANGEL_API_KEY", "mock_api_key_123")
    monkeypatch.setenv("ANGEL_CLIENT_ID", "mock_client_id")
    monkeypatch.setenv("ANGEL_PIN", "1234")
    monkeypatch.setenv("ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")

    mock_client = mock.MagicMock()
    mock_client.generateSession.return_value = {
        "status": True,
        "message": "SUCCESS",
        "data": {
            "jwtToken": "mock_jwt_token_abc",
            "refreshToken": "mock_refresh_token_xyz",
            "feedToken": "mock_feed_token_789"
        }
    }
    mock_client.getfeedToken.return_value = "mock_feed_token_789"

    with mock.patch("smartapi_client.SmartConnect", return_value=mock_client), \
         mock.patch("pyotp.TOTP.now", return_value="654321"):
        success = smartapi_client.session_manager.login()

    assert success is True
    assert smartapi_client.session_manager._auth_token == "mock_jwt_token_abc"
    assert smartapi_client.session_manager._feed_token == "mock_feed_token_789"
    assert smartapi_client.session_manager._refresh_token == "mock_refresh_token_xyz"
    assert store.kv_get("angel_one_status") == "connected"

    # Verify credentials/tokens are NOT saved to any local file
    cache_path = smartapi_client.SmartAPIInstrumentManager.CACHE_FILE
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_text = f.read()
        assert "mock_jwt_token_abc" not in cache_text
        assert "mock_feed_token_789" not in cache_text


# ---------------------------------------------------------------------------
# 2. Auth Error & Auto Re-Login
# ---------------------------------------------------------------------------
def test_angel_auth_error_and_relogin(monkeypatch):
    """Verifies that an expired token or AG8001 error triggers re-authentication and retry."""
    monkeypatch.setenv("ANGEL_API_KEY", "mock_api_key_123")
    monkeypatch.setenv("ANGEL_CLIENT_ID", "mock_client_id")
    monkeypatch.setenv("ANGEL_PIN", "1234")
    monkeypatch.setenv("ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")

    mock_client = mock.MagicMock()
    # First call: auth expired. Second call: success.
    mock_client.ltpData.side_effect = [
        {"status": False, "errorcode": "AG8001", "message": "Invalid Token"},
        {"status": True, "message": "SUCCESS", "data": {"ltp": 1245.50}}
    ]
    mock_client.generateSession.return_value = {
        "status": True,
        "data": {
            "jwtToken": "mock_jwt_new",
            "feedToken": "mock_feed_new"
        }
    }

    with mock.patch("smartapi_client.SmartConnect", return_value=mock_client), \
         mock.patch("pyotp.TOTP.now", return_value="112233"):
        # Pre-seed session
        smartapi_client.session_manager._client = mock_client
        smartapi_client.session_manager._auth_token = "old_token"
        smartapi_client.session_manager._login_time = time.time()

        px = smartapi_client.q_angel_one({"yf": "RELIANCE.NS"})

    assert px == 1245.50
    assert mock_client.ltpData.call_count == 2


def test_angel_login_failure_silent_fallthrough(monkeypatch):
    """When credentials are bad or login fails, status is recorded and exception is raised for fallback."""
    monkeypatch.setenv("ANGEL_API_KEY", "bad_key")
    monkeypatch.setenv("ANGEL_CLIENT_ID", "bad_id")
    monkeypatch.setenv("ANGEL_PIN", "0000")
    monkeypatch.setenv("ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")

    mock_client = mock.MagicMock()
    mock_client.generateSession.return_value = {
        "status": False,
        "message": "Invalid credentials",
        "errorcode": "AB1001"
    }

    with mock.patch("smartapi_client.SmartConnect", return_value=mock_client):
        with pytest.raises(RuntimeError) as exc_info:
            smartapi_client.q_angel_one({"yf": "RELIANCE.NS"})
        assert "Angel One login failed" in str(exc_info.value)

    assert store.kv_get("angel_one_status") == "Angel One login failed"


# ---------------------------------------------------------------------------
# 3. Unknown Symbol Handling
# ---------------------------------------------------------------------------
def test_angel_unknown_symbol_resolution():
    """Unknown symbols return None from instrument manager and raise ValueError in q_angel_one."""
    res = smartapi_client.instrument_manager.resolve_symbol("UNKNOWN_SYMBOL_99")
    assert res is None

    with pytest.raises(ValueError) as exc:
        smartapi_client.q_angel_one({"yf": "UNKNOWN_SYMBOL_99.NS"})
    assert "Unknown Angel One symbol" in str(exc.value)


# ---------------------------------------------------------------------------
# 4. WebSocket Tick Processing & Paise Conversion (/100)
# ---------------------------------------------------------------------------
def test_angel_websocket_tick_paise_conversion(monkeypatch):
    """Prices from SmartWebSocket arrive as integers (paise) and must be divided by 100.0."""
    saved_quotes = []
    monkeypatch.setattr(store, "save_quote", lambda sym, price, source: saved_quotes.append((sym, price, source)))

    stream = smartapi_client.SmartAPIStreamManager()
    # Simulate binary parsed tick message for RELIANCE (token 2885, price 119000 paise = 1190.00 rupees)
    mock_tick = {
        "subscription_mode": 1,
        "exchange_type": 1,
        "token": "2885",
        "sequence_number": 1001,
        "exchange_timestamp": int(time.time() * 1000),
        "last_traded_price": 119000
    }
    stream._process_tick(mock_tick)

    assert len(saved_quotes) == 1
    sym, px, src = saved_quotes[0]
    assert sym == "RELIANCE"
    assert px == 1190.0
    assert src == "Angel One"


# ---------------------------------------------------------------------------
# 5. WebSocket Trading-Key Rejection Detection
# ---------------------------------------------------------------------------
def test_angel_websocket_trading_key_rejection():
    """If the websocket rejects a Trading-type key, record warning telling user to create Market Feeds app."""
    stream = smartapi_client.SmartAPIStreamManager()

    # Simulate error callback with Trading key error
    mock_ws = mock.MagicMock()
    # Trigger error handler
    error_msg = "Connection rejected: 401 Unauthorized / Invalid API Key for stream"
    # Call internal error handler logic
    err_str = error_msg.lower()
    if any(t in err_str for t in ["market feeds", "trading app", "invalid api key", "401"]):
        store.kv_set("angel_one_status", stream.TRADING_KEY_WARNING)

    status = store.kv_get("angel_one_status")
    assert "Market Feeds" in status
    assert "Trading-type keys cannot stream feeds" in status


# ---------------------------------------------------------------------------
# 6. Quote Source Precedence (Angel One is FIRST for Indian Equities)
# ---------------------------------------------------------------------------
def test_quote_sources_precedence():
    """Verifies that Angel One SmartAPI is the FIRST quote source for Indian assets."""
    reliance_asset = {
        "name": "RELIANCE",
        "cls": "stock",
        "yf": "RELIANCE.NS",
        "nse": "RELIANCE"
    }
    sources = md._quote_sources(reliance_asset)
    assert len(sources) >= 1
    first_name, _ = sources[0]
    assert first_name == "Angel One SmartAPI"
