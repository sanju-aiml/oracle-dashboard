"""The 'train -> test -> validate -> if it fails, fix and train again' loop.
Honest design points:
 * Retraining until a metric passes is multiple testing. Each round increments n_trials and the market gate uses
   the DEFLATED Sharpe, so passing by luck gets harder every round.
 * A final holdout (last `holdout_frac` of dates) is NEVER used for training or for choosing fixes.
 * If max_rounds is reached without passing, the run FAILS and nothing is promoted. 'Never fails' cannot be
   guaranteed for markets; what this guarantees is that nothing failing gets deployed."""
from __future__ import annotations
import json, os, time
from dataclasses import dataclass, field

@dataclass
class GateResult:
    passed: bool
    checks: dict
    metrics: dict

def check(cfg_gate: dict, market: dict, llm: dict) -> GateResult:
    c = {
        "beats_naive": market["acc_vs_naive"] >= cfg_gate["min_direction_acc_vs_naive"],
        "sharpe": market["sharpe_after_costs"] >= cfg_gate["min_sharpe_after_costs"],
        "deflated_sharpe": market["deflated_sharpe_prob"] >= 0.80,
        "drawdown": market["max_drawdown"] <= cfg_gate["max_drawdown"],
        "json": llm["json_validity"] >= cfg_gate["min_json_validity"],
        "hallucination": llm["hallucination_rate"] <= cfg_gate["max_hallucination_rate"],
        "calc": llm["calc_accuracy"] >= cfg_gate["min_calc_accuracy"],
    }
    return GateResult(all(c.values()), c, {"market": market, "llm": {k: v for k, v in llm.items() if k != "calc_failures"}})

def remedies(res: GateResult, llm: dict, cfg: dict, round_i: int) -> dict:
    """Deterministic fixes mapped to failed checks. Returns config/data patches for the next round."""
    patch = {"lr": cfg["lr"] * (0.7 if round_i % 2 else 1.0), "extra_calc": 0, "extra_tool": 0, "extra_json": 0,
             "min_edge": None, "signal_kw": {}}
    ch = res.checks
    if not ch["calc"]:
        patch["extra_calc"] = 4000 * (round_i + 1)                  # oversample the kinds the model failed
        kinds = {}
        for f in llm.get("calc_failures", []):
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        patch["hard_kinds"] = kinds
    if not ch["hallucination"]:
        patch["extra_tool"] = 2000 * (round_i + 1)
    if not ch["json"]:
        patch["extra_json"] = 4000 * (round_i + 1)
    if not (ch["sharpe"] and ch["beats_naive"] and ch["deflated_sharpe"]):
        # regularise the signal model harder & demand a bigger edge before trading (less overfit, fewer trades)
        patch["signal_kw"] = {"max_depth": max(2, 4 - round_i), "min_samples_leaf": 200 + 200 * round_i,
                              "l2_regularization": 1.0 + 2.0 * round_i}
        patch["min_edge"] = 0.05 + 0.03 * round_i
    return patch

def log_round(path: str, i: int, res: GateResult, patch: dict | None):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"round": i, "ts": time.time(), "passed": res.passed, "checks": res.checks,
                            "metrics": res.metrics, "next_patch": patch}, default=str) + "\n")
