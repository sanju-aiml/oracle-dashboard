# ORACLE AI Bot Cloud Training Guide (Google Colab / RunPod / Lambda)

Follow these step-by-step cells to train the fine-tuned 7B model (**Qwen2.5-7B-Instruct**) on a cloud GPU (A100 or L4 recommended). **Never train from scratch**; training uses QLoRA 4-bit with completion-only loss.

---

## 1. Google Colab Instructions

Open a new Google Colab notebook with an **A100 (40GB/80GB)** or **L4 GPU** runtime:
*(Runtime > Change runtime type > T4/L4/A100 GPU)*

### Cell 1: Verify GPU & Mount Google Drive
```python
# Cell 1: GPU + Drive
!nvidia-smi
from google.colab import drive
drive.mount('/content/drive')
```

### Cell 2: Clone Repository & Install Training Dependencies
```bash
# Cell 2: code
!git clone https://github.com/<you>/<repo>.git /content/oracle && cd /content/oracle && pip install -q -r requirements-train.txt
```
*(Replace `<you>/<repo>` with your GitHub repository URL)*

### Cell 3: Dry-Run Plan Check (No GPU Computation)
Verify the parameters, conversation counts, and optimizer steps:
```bash
# Cell 3: plan only (no GPU work) - check numbers
!cd /content/oracle && python scripts/train_cloud.py --dry-run
```
Expected output:
```text
PLAN base=Qwen/Qwen2.5-7B-Instruct conversations=1,500,000 max_steps=100,000 eff_batch=32 drive=/content/drive/MyDrive/oracle-ai
     records seen = 3,200,000; early stopping patience = 10 evals x 1000 steps
```

### Cell 4: Launch Training (Resume-Safe)
```bash
# Cell 4: run (resume-safe; re-run after any disconnect)
!cd /content/oracle && python scripts/train_cloud.py --drive-root /content/drive/MyDrive/oracle-ai
```

---

## 2. Handling Disconnections & Resuming
- Checkpoints are saved periodically and copied atomically to Google Drive under `MyDrive/oracle-ai/checkpoints/round0/checkpoint-N`.
- If Colab disconnects, simply reconnect the GPU runtime and **re-run Cell 4**.
- The script automatically detects the latest valid checkpoint on Drive, restores it, and resumes training seamlessly from step `N`.

---

## 3. Alternative Cloud GPU: RunPod / Lambda (A100)
1. Open a terminal in the pod with a persistent network volume mounted at `/workspace`.
2. Run:
```bash
git clone https://github.com/<you>/<repo>.git /workspace/oracle
cd /workspace/oracle
pip install -q -r requirements-train.txt
python scripts/train_cloud.py --drive-root /workspace/oracle-ai
```
3. Checkpoints and exported models will persist in `/workspace/oracle-ai`.

---

## 4. Monitoring Training & Gate Verification
- **Loss Progression**: Inspect `/content/drive/MyDrive/oracle-ai/checkpoints/round0/train_log.jsonl`. Training loss falls rapidly in the first 1–2k steps, then stabilizes; validation loss is evaluated every 1,000 steps.
- **Evaluation Gate**: After training completes, the script evaluates the held-out test split across all 8 quality dimensions (tool accuracy, JSON validity, hallucination rate, exact calculation grounding, language match, refusal accuracy, prompt injection resistance, and status honesty).
- **Repairs**: If a gate check fails, up to 4 repair rounds are automatically executed with targeted up-weighting and 5,000 repair steps at `lr=3e-5`.

---

## 5. Artifact Export & Bringing Model to Laptop
Once the gate passes, the script automatically:
1. Merges the LoRA adapter into the bf16 base model (`models/merged-fp16`).
2. Converts the merged model to GGUF format with `llama.cpp` (`models/model-f16.gguf`).
3. Quantizes the weights to `Q4_K_M` (`models/model-q4.gguf`).
4. Generates the Ollama `Modelfile`.

Download `model-q4.gguf` and `Modelfile` from your Drive folder (`MyDrive/oracle-ai/models/`) onto your laptop:
```bash
# On your local laptop inside the folder with model-q4.gguf and Modelfile:
ollama create oracle-bot -f Modelfile
set ORACLE_LLM_URL=http://127.0.0.1:11434/v1/chat/completions
set ORACLE_LLM_MODEL=oracle-bot
python server.py
```
