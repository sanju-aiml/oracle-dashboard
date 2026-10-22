"""Comprehensive Test Suite for FinLLM Model Integration in ORACLE
Verifies trained Quant Signal model, DeepLOB PyTorch neural network,
CA calculators, anti-hallucination agent runtime, and FastAPI routes.
"""
import pytest
from fastapi.testclient import TestClient
import finllm_engine
from server import app

client = TestClient(app)

def test_1_finllm_model_status():
    st = finllm_engine.get_model_status()
    assert st["status"] == "ready"
    assert st["signal_model_loaded"] is True
    assert st["deeplob_neural_net_loaded"] is True
    assert "HistGradientBoostingClassifier" in st["architecture"]["signal_classifier"]
    assert "DeepLOB" in st["architecture"]["neural_network"]
    assert st["training_summary"]["market_metrics"]["hit_rate_when_trading"] > 0.50

def test_2_finllm_predict_signal_amzn():
    sig = finllm_engine.predict_signal("AMZN")
    assert sig["status"] == "ok"
    assert sig["kind"] == "forecast"
    assert sig["symbol"] == "AMZN"
    assert sig["view"] in ("bullish", "bearish", "neutral")
    assert sig["action"] in ("buy", "sell", "abstain")
    probs = sig["probabilities"]
    assert 0.0 <= probs["p_up"] <= 1.0
    assert 0.0 <= probs["p_flat"] <= 1.0
    assert 0.0 <= probs["p_down"] <= 1.0
    assert abs(probs["p_up"] + probs["p_flat"] + probs["p_down"] - 1.0) < 0.05
    assert "rsi_14" in sig["indicators"]
    assert sig["model_provenance"]["walk_forward_hit_rate"] == "51.48%"

def test_3_finllm_predict_diverse_assets():
    for sym in ["RELIANCE.NS", "BTC", "GOLD", "AAPL"]:
        sig = finllm_engine.predict_signal(sym)
        assert sig["status"] == "ok"
        assert sig["symbol"] == sym.upper()
        assert sig["confidence"] >= 0.0

def test_4_finllm_deeplob_microstructure_inference():
    res = finllm_engine.run_deeplob_signal("NVDA")
    assert res["status"] == "ok"
    assert res["kind"] == "forecast"
    assert res["symbol"] == "NVDA"
    assert "DeepLOB" in res["architecture"]
    probs = res["probabilities"]
    assert abs(probs["down"] + probs["flat"] + probs["up"] - 1.0) < 0.01

def test_5_finllm_ca_banking_calculators():
    # GST
    gst_res = finllm_engine.calculate_ca_banking("gst", {"amount": 100000, "rate_pct": 18})
    assert gst_res["status"] == "ok"
    assert gst_res["result"]["gst"] == 18000.0
    assert gst_res["result"]["total"] == 118000.0
    assert gst_res["result"]["cgst"] == 9000.0

    # EMI
    emi_res = finllm_engine.calculate_ca_banking("emi", {"principal": 1000000, "rate_pct": 9.0, "tenure_years": 10})
    assert emi_res["status"] == "ok"
    assert abs(emi_res["result"]["emi"] - 12667.58) < 1.0

    # Income tax new regime
    tax_res = finllm_engine.calculate_ca_banking("tax_new_regime", {"income": 1275000})
    assert tax_res["status"] == "ok"
    assert tax_res["result"]["total"] == 0.0 # 87A rebate edge

    # TDS 194C
    tds_pan = finllm_engine.calculate_ca_banking("tds_194c", {"amount": 50000, "pan": True, "individual": True})
    assert tds_pan["result"]["tds"] == 500.0 # 1% individual rate
    tds_nopan = finllm_engine.calculate_ca_banking("tds_194c", {"amount": 50000, "pan": False})
    assert tds_nopan["result"]["tds"] == 10000.0 # 20% penalty rate without PAN

def test_6_finllm_fastapi_endpoints():
    # Status
    r = client.get("/api/finllm/status")
    assert r.status_code == 200
    assert r.json()["status"] == "ready"

    # Signal GET
    r = client.get("/api/finllm/signal?symbol=AMZN")
    assert r.status_code == 200
    assert r.json()["symbol"] == "AMZN"

    # Signal POST
    r = client.post("/api/finllm/signal", json={"symbol": "MSFT"})
    assert r.status_code == 200
    assert r.json()["symbol"] == "MSFT"

    # DeepLOB GET
    r = client.get("/api/finllm/deeplob?symbol=AMZN")
    assert r.status_code == 200
    assert "probabilities" in r.json()

    # Calc POST
    r = client.post("/api/finllm/calc", json={"type": "gst", "params": {"amount": 50000, "rate_pct": 18}})
    assert r.status_code == 200
    assert r.json()["result"]["total"] == 59000.0

    # Chat POST
    r = client.post("/api/finllm/chat", json={"message": "What is the GST on 20000 at 18%?"})
    assert r.status_code == 200
    assert "answer" in r.json()

def test_7_core_chat_integrated_finllm_ca():
    import core
    # Chat should handle GST
    gst_reply = core.chat("What is GST on 50000 at 18%?", None)
    assert "59,000" in gst_reply or "9,000" in gst_reply

    # Chat should handle EMI
    emi_reply = core.chat("Calculate EMI on loan 1000000 at 9% for 10 years", None)
    assert "12,668" in emi_reply or "12,667" in emi_reply

    # Chat should handle Amazon investment
    amzn_reply = core.chat("Amazon lo invest cheyocha?", None)
    assert "AMZN" in amzn_reply or "Amazon" in amzn_reply

def test_8_binance_live_crypto_and_candles():
    import market
    # Verify Binance live crypto quote
    btc = market.get_crypto_price("BTC")
    assert btc["status"] == "ok"
    assert btc["kind"] == "actual"
    assert btc["price"] > 10000.0
    assert "Binance" in btc["provider_name"]

    # Verify Binance live OHLCV klines
    ohlcv = market.get_ohlcv("BTC", outputsize=15)
    assert ohlcv["status"] == "ok"
    assert ohlcv["kind"] == "actual"
    assert len(ohlcv["candles"]) > 0
    assert "Binance" in ohlcv["provider_name"]
    latest = ohlcv["candles"][-1]
    assert latest["open"] > 0
    assert latest["close"] > 0
    assert latest["high"] >= latest["low"]
