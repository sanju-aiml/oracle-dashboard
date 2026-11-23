"""Generators: messages -> assistant text. hf_generator (eval on GPU) and http_generator (Ollama / llama.cpp / vLLM, used by ORACLE at runtime)."""
from __future__ import annotations
import json, urllib.request

def http_generator(url="http://127.0.0.1:11434/v1/chat/completions", model="oracle-bot", max_tokens=400, timeout=60):
    def gen(messages):
        body = json.dumps({"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens, "stream": False}).encode()
        req = urllib.request.Request(url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]
    return gen

def hf_generator(base: str, adapter: str | None = None, quant=True, max_new_tokens=300):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    tok = AutoTokenizer.from_pretrained(adapter or base)
    bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16) if quant and torch.cuda.is_available() else None
    m = AutoModelForCausalLM.from_pretrained(base, quantization_config=bnb, torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                                             device_map="auto" if torch.cuda.is_available() else None)
    if adapter:
        from peft import PeftModel
        m = PeftModel.from_pretrained(m, adapter)
    m.eval()
    def gen(messages):
        enc = tok.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt")
        if hasattr(enc, "to"):
            enc = enc.to(m.device)
        if isinstance(enc, dict) or hasattr(enc, "data"):
            input_ids = enc["input_ids"]
            kwargs = {k: v for k, v in enc.items()}
        else:
            input_ids = enc
            kwargs = {"input_ids": input_ids}
        with torch.no_grad():
            out = m.generate(**kwargs, max_new_tokens=max_new_tokens, do_sample=False, pad_token_id=tok.pad_token_id or tok.eos_token_id)
        return tok.decode(out[0, input_ids.shape[1]:], skip_special_tokens=True)
    return gen
