#!/usr/bin/env bash
# One command on a GPU box (>=24GB VRAM). Trains 7B QLoRA, evaluates, gates, retries up to max_rounds.
set -euo pipefail
pip install -r requirements.txt
python -m finllm.train.pipeline --config configs/train_7b.yaml --start 2012-01-01
echo "serve: FINLLM_BASE=Qwen/Qwen2.5-7B-Instruct FINLLM_MODEL=runs/finllm-7b/PROMOTED uvicorn finllm.serve.api:app --port 8000"
