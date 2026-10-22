import json, numpy as np, pandas as pd, pytest
from finllm.features.ta import build_features, make_labels, rolling_zscore
from finllm.signal.model import build_panel, walk_forward_predict
from finllm.backtest.engine import walk_forward_splits, metrics, deflated_sharpe
from finllm.data import calc, sft_builder as sb
from finllm.train import evaluate, gate
from finllm.agent.runtime import Agent
from finllm.agent.tools import Tools
from finllm.marketing import bot

def synth(n=1800, syms=("A", "B", "C"), seed=0):
    rng = np.random.default_rng(seed); rows = []
    for s in syms:
        r = rng.normal(0.0003, 0.012, n); c = 100 * np.exp(np.cumsum(r))
        d = pd.bdate_range("2015-01-01", periods=n)
        rows.append(pd.DataFrame({"date": d, "symbol": s, "open": c, "high": c * 1.01, "low": c * .99, "close": c, "volume": rng.integers(1e5, 1e6, n)}))
    return pd.concat(rows, ignore_index=True)

def test_features_no_lookahead():
    p = synth(); g = p[p.symbol == "A"].reset_index(drop=True)
    f1 = build_features(g)
    g2 = g.copy(); g2.loc[1500:, "close"] *= 3          # change the future
    f2 = build_features(g2)
    cols = [c for c in f1.columns if c not in ("date", "symbol")]
    pd.testing.assert_frame_equal(f1.loc[:1499, cols], f2.loc[:1499, cols])

def test_splits_purged():
    d = pd.Series(pd.bdate_range("2015-01-01", periods=1000))
    for tr, te in walk_forward_splits(d, horizon=5, embargo=5):
        assert tr.max() < te.min() and (len(d[(d > tr.max()) & (d < te.min())]) >= 10)

def test_walk_forward_and_eval_on_noise_fails_gate():
    panel = build_panel(synth())
    preds = walk_forward_predict(panel, n_splits=3)
    m = evaluate.eval_market(preds, n_trials=6)
    assert m["deflated_sharpe_prob"] < 0.95            # pure noise must not look like alpha
    llm = {"json_validity": 1, "hallucination_rate": 0, "calc_accuracy": 1}
    res = gate.check({"min_direction_acc_vs_naive": .02, "min_sharpe_after_costs": .5, "max_drawdown": .25,
                      "min_json_validity": .99, "max_hallucination_rate": .02, "min_calc_accuracy": .98}, m, llm)
    assert not res.passed

def test_calc_truth():
    assert calc.gst(1000, 18)["total"] == 1180
    assert abs(calc.emi(1_000_000, 9, 10)["emi"] - 12667.58) < 0.1
    assert calc.tax_new_regime(1_200_000 + 75000)["total"] == 0.0     # 87A rebate edge
    assert calc.tds_194c(50000, pan=False)["tds"] == 10000

def test_sft_examples_and_oracle_gen_passes_llm_eval():
    rows = sb.calc_examples(50) + sb.tool_trace_examples(10)
    assert all(r["messages"][-1]["content"] for r in rows)
    def oracle(msgs):
        q = msgs[-1]["content"]
        for m_, ans in [(c[0][-1]["content"], c[1]) for c in evaluate.calc_cases(200)]:
            if m_ == q: return f"{ans}"
        if "trading at right now" in q:
            return json.dumps({"tool": "get_quote", "args": {"symbol": q.split()[2]}})
        return json.dumps({"view": "neutral", "probabilities": {}, "confidence": .5, "action": "abstain"})
    r = evaluate.eval_llm(oracle)
    assert r["calc_accuracy"] == 1 and r["json_validity"] == 1 and r["hallucination_rate"] == 0
    bad = evaluate.eval_llm(lambda m: "It is about 100")
    assert bad["calc_accuracy"] < .1 and bad["hallucination_rate"] == 1

def test_agent_blocks_execution_and_guarantees(tmp_path):
    seq = iter([json.dumps({"tool": "place_order", "args": {}})])
    a = Agent(lambda m: next(seq), Tools(), "s", audit_path=str(tmp_path / "a.jsonl"))
    assert a.run("buy")["escalated_to_human"]
    a2 = Agent(lambda m: "This is a guaranteed return fund", Tools(), "s", audit_path=str(tmp_path / "b.jsonl"))
    assert a2.run("x")["escalated_to_human"]
    seq2 = iter([json.dumps({"tool": "gst", "args": {"amount": 100, "rate_pct": 18}}), "Total ₹118"])
    a3 = Agent(lambda m: next(seq2), Tools(), "s", audit_path=str(tmp_path / "c.jsonl"))
    assert a3.run("gst?")["answer"] == "Total ₹118"

def test_marketing_compliance():
    assert bot.compliance_check("Get guaranteed returns now", True)
    c = bot.Customer("1", consent_marketing=False)
    assert not bot.can_contact(c, "whatsapp")[0]
    b = bot.ThompsonBandit(["a", "b"], seed=1)
    for _ in range(300): b.update("a", np.random.rand() < .3); b.update("b", np.random.rand() < .05)
    assert sum(b.pick() == "a" for _ in range(200)) > 150

def test_live_cache(tmp_path):
    from finllm.serve.live import LiveCache
    def bad(s):
        if s == "X": raise RuntimeError("down")
        return {"symbol": s, "price": 1.0}
    c = LiveCache(path=str(tmp_path / "c.json"), symbols=["A", "X"], fetch_quote=bad,
                  fetch_news=lambda: pd.DataFrame({"ts": [pd.Timestamp("2026-01-01")], "source": ["s"], "title": ["t"], "link": ["l"]}))
    st = c.refresh()
    assert st["quotes"]["A"]["price"] == 1.0 and "error" in st["quotes"]["X"] and not c.stale()
