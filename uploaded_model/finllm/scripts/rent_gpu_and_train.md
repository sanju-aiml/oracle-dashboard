# Train on a rented GPU (cheapest path)
1. RunPod / Lambda / Vast.ai: 1x A100 80GB (or 1x 4090 24GB, slower). Image: PyTorch 2.x CUDA 12.
2. `git clone` or upload finllm.zip; `cd finllm && bash scripts/run_all.sh`
3. Watch `runs/finllm-7b/gate_log.jsonl`. Send it to Claude if a round fails.
4. Serve: `python -m finllm.serve.live &` then the uvicorn command printed by run_all.sh.
Rough cost: ~6-10 GPU-hours/round on an A100 for this corpus size.
