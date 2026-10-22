"""End-to-end orchestration:  data -> signal walk-forward -> SFT corpus -> QLoRA train -> eval -> gate -> (fix, repeat).
python -m finllm.train.pipeline --config configs/train_7b.yaml --start 2012-01-01"""
from __future__ import annotations
import argparse, os, yaml
import pandas as pd
from ..data import market, sft_builder as sb
from ..signal.model import build_panel, walk_forward_predict
from ..features.ta import build_features
from . import evaluate, gate

def holdout_split(panel: pd.DataFrame, frac=0.15):
    dates = sorted(panel["date"].unique())
    cut = dates[int(len(dates) * (1 - frac))]
    return panel[panel["date"] < cut], panel[panel["date"] >= cut], cut

def make_generator(model_dir: str, base: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import PeftModel
    tok = AutoTokenizer.from_pretrained(model_dir)
    m = AutoModelForCausalLM.from_pretrained(base, quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16),
                                             device_map="auto")
    m = PeftModel.from_pretrained(m, model_dir).eval()
    def gen(messages):
        ids = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to(m.device)
        with torch.no_grad():
            out = m.generate(ids, max_new_tokens=400, do_sample=False)
        return tok.decode(out[0, ids.shape[1]:], skip_special_tokens=True)
    return gen

def run(cfg_path: str, start="2012-01-01", prices_path: str | None = None, dry_run=False):
    cfg = yaml.safe_load(open(cfg_path))
    os.makedirs("data", exist_ok=True)
    prices = pd.read_parquet(prices_path) if prices_path else market.fetch_history(market.all_symbols(), start=start)
    prices.to_parquet("data/prices.parquet")
    panel = build_panel(prices)
    dev, hold, cut = holdout_split(panel)
    print(f"dev rows {len(dev)} | holdout from {cut}")
    patch = {"signal_kw": {}, "min_edge": 0.05, "extra_calc": 0, "extra_tool": 0, "extra_json": 0}
    g = cfg["gate"]
    prev_dir = None
    for rnd in range(g["max_rounds"]):
        # 1) signal model: walk-forward on DEV only, then a fixed fit-on-dev / predict-on-holdout for the gate
        dev_preds = walk_forward_predict(dev, seed=rnd, **patch["signal_kw"])
        hold_preds = _holdout_preds(dev, hold, rnd, patch["signal_kw"])
        # 2) corpus (market answers come from DEV out-of-sample preds only)
        rows = (sb.market_examples(dev_preds, dev, max_n=20000, seed=rnd)
                + sb.calc_examples(6000, seed=rnd)
                + sb.calc_examples(patch["extra_calc"], seed=rnd + 1000, kinds=_hard_kinds(patch))
                + sb.tool_trace_examples(2000 + patch["extra_tool"], seed=rnd))
        rows = [r for r in rows if r["as_of"] == "static" or r["as_of"] < str(cut.date())]
        import random; random.Random(rnd).shuffle(rows)
        k = int(len(rows) * 0.98)
        sb.write_jsonl(rows[:k], "data/sft_train.jsonl"); sb.write_jsonl(rows[k:], "data/sft_val.jsonl")
        if dry_run:
            print("dry run: corpus built", len(rows)); return
        # 3) train 7B QLoRA (continues from previous round's adapter weights are NOT merged; each round retrains from base
        #    on the corrected corpus so failures are attributable to data, not accumulated drift)
        from .sft import train
        c = dict(cfg); c["lr"] = cfg["lr"] * (0.7 ** rnd)
        out = train(c, rows[:k], rows[k:], out_dir=f"{cfg['output_dir']}/round{rnd}")
        # 4) evaluate
        gen = make_generator(out, cfg["base_model"])
        market_m = evaluate.eval_market(hold_preds, cost_bps=g["cost_bps"], n_trials=rnd + 1, min_edge=patch["min_edge"] or 0.05)
        llm_m = evaluate.eval_llm(gen)
        res = gate.check(g, market_m, llm_m)
        patch = gate.remedies(res, llm_m, cfg, rnd) if not res.passed else None
        gate.log_round(f"{cfg['output_dir']}/gate_log.jsonl", rnd, res, patch)
        print(f"round {rnd}: {'PASS' if res.passed else 'FAIL'} {res.checks}")
        if res.passed:
            link = os.path.abspath(f"{cfg['output_dir']}/PROMOTED")
            if os.path.lexists(link):
                os.remove(link)
            os.symlink(os.path.abspath(out), link, target_is_directory=True)
            return out
    raise SystemExit("GATE NOT PASSED after max_rounds — model NOT promoted. See gate_log.jsonl.")

def _hard_kinds(patch):
    m = {"gst": "gst", "emi": "emi", "tax": "tax_new_regime"}
    ks = [m[k] for k in (patch.get("hard_kinds") or {}) if k in m]
    return ks or None

def _holdout_preds(dev, hold, seed, kw):
    from ..signal.model import _model, feature_cols
    cols = feature_cols(dev)
    tr = dev[dev["label"] >= 0].dropna(subset=cols)
    tr = tr[tr["date"] < tr["date"].max() - pd.Timedelta(days=14)]    # purge/embargo before holdout
    te = hold[hold["label"] >= 0].dropna(subset=cols)
    m = _model(seed, **kw).fit(tr[cols], tr["label"])
    pr = m.predict_proba(te[cols]); cls = list(m.classes_)
    r = te[["date", "symbol", "label", "fwd_ret", "fwd1"]].copy()
    for k, nm in ((0, "p_down"), (1, "p_flat"), (2, "p_up")):
        r[nm] = pr[:, cls.index(k)] if k in cls else 0.0
    r["majority"] = tr["label"].mode().iloc[0]
    return r

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/train_7b.yaml"); ap.add_argument("--start", default="2012-01-01")
    ap.add_argument("--prices"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    run(a.config, a.start, a.prices, a.dry_run)
