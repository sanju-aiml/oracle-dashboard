# FinLLM — 7B+ finance LLM (India + global: stocks, gold, oil, FX, crypto) for CAs, bankers, investors

## What the papers dictated
| Paper | Used for |
|---|---|
| DeepLOB (1808.03668) | past-only rolling z-score, smoothed-mean labels with dead-zone, DeepLOB net (`signal/model.py`) |
| Survey: LLM-enhanced RL in financial markets (2026) | strict time alignment (no look-ahead), memorisation risk, MVO baseline, feature/auxiliary/policy coupling → we use the *auxiliary* mode: LLM reasons, quant model gives numbers |
| Millea, DRL for Trading (2021) | Sharpe/Sortino metrics, UCRP/B&H baselines, multi-timescale inputs, prediction/strategy/portfolio/risk split |
| Measuring Agents in Production (2026) | bounded ≤10-step workflow, custom loop, human approval for execution, rule+LLM verification, audit log, prompts/tools over weight-tuning where possible |
| Agentic AI in business review (2026) | autonomy levels: decision-support by default, governance/accountability → `agent/runtime.py` |
(ScienceDirect link was not readable by automated tools; send the PDF to include it.)

## Run (GPU ≥24 GB)
`bash scripts/run_all.sh` → fetch data → walk-forward signal → SFT corpus → QLoRA 7B → eval → gate → retrain on failures (≤6 rounds) → `runs/finllm-7b/PROMOTED`.
Serve: `FINLLM_BASE=Qwen/Qwen2.5-7B-Instruct FINLLM_MODEL=runs/finllm-7b/PROMOTED uvicorn finllm.serve.api:app`.
Tests (CPU): `pytest tests`.

## Hard truths
* No one can make a model that "never fails" at predicting markets. The gate guarantees a failing model is never promoted; it uses deflated Sharpe because retrain-until-pass is multiple testing.
* The LLM never supplies prices or arithmetic; tools do (live quotes, calculators, signal model, RAG).
* Update `data/calc.py` tax slabs each Budget. Add real RBI/SEBI/IT/GST docs to the RAG store.
* Regulatory: personalised investment advice in India needs SEBI RIA registration; keep it decision-support.
* Training on the 7B was NOT run here (no GPU); the pipeline, gate and tools were tested on CPU with synthetic data.
