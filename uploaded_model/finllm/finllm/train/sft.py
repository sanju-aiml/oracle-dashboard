"""QLoRA supervised fine-tuning of a 7B+ base model. Run on a GPU box (24GB+ VRAM for 4-bit 7B; 1x A100/H100 ideal).
python -m finllm.train.sft --config configs/train_7b.yaml --data data/sft_train.jsonl --val data/sft_val.jsonl"""
from __future__ import annotations
import argparse, json, yaml

def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]

def train(cfg: dict, train_rows: list[dict], val_rows: list[dict], out_dir: str | None = None, resume_from: str | None = None):
    import torch
    from datasets import Dataset
    from peft import LoraConfig, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    out_dir = out_dir or cfg["output_dir"]
    tok = AutoTokenizer.from_pretrained(cfg["base_model"], use_fast=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                             bnb_4bit_use_double_quant=True) if cfg.get("quant_4bit", True) else None
    model = AutoModelForCausalLM.from_pretrained(resume_from or cfg["base_model"], quantization_config=bnb,
                                                 torch_dtype=torch.bfloat16, device_map="auto")
    if bnb:
        model = prepare_model_for_kbit_training(model)
    lora = LoraConfig(r=cfg["lora"]["r"], lora_alpha=cfg["lora"]["alpha"], lora_dropout=cfg["lora"]["dropout"],
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
                      task_type="CAUSAL_LM")
    to_ds = lambda rows: Dataset.from_list([{"messages": r["messages"]} for r in rows])
    args = SFTConfig(output_dir=out_dir, num_train_epochs=cfg["epochs"], learning_rate=cfg["lr"],
                     per_device_train_batch_size=cfg["batch_size"], gradient_accumulation_steps=cfg["grad_accum"],
                     lr_scheduler_type="cosine", warmup_ratio=0.03, bf16=True, logging_steps=20,
                     eval_strategy="steps", eval_steps=200, save_steps=200, save_total_limit=2,
                     load_best_model_at_end=True, metric_for_best_model="eval_loss", greater_is_better=False,
                     max_length=cfg["max_seq_len"], gradient_checkpointing=True, packing=False,
                     assistant_only_loss=False, report_to="none")
    try:
        trainer = SFTTrainer(model=model, args=args, train_dataset=to_ds(train_rows), eval_dataset=to_ds(val_rows),
                             peft_config=lora, processing_class=tok)
    except TypeError:                                              # older trl
        trainer = SFTTrainer(model=model, args=args, train_dataset=to_ds(train_rows), eval_dataset=to_ds(val_rows),
                             peft_config=lora, tokenizer=tok)
    trainer.train()
    trainer.save_model(out_dir)
    tok.save_pretrained(out_dir)
    return out_dir

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True); ap.add_argument("--data", required=True); ap.add_argument("--val", required=True)
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config))
    print(train(cfg, load_jsonl(a.data), load_jsonl(a.val)))
