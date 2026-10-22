"""uvicorn finllm.serve.api:app --port 8000   (set FINLLM_MODEL to the promoted adapter dir; FINLLM_BASE to base model)"""
from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from ..agent.tools import Tools
from ..agent.runtime import Agent
from ..data.sft_builder import SYSTEM

app = FastAPI(title="FinLLM")
_state: dict = {}

def _gen():
    if "gen" not in _state:
        from ..train.pipeline import make_generator
        _state["gen"] = make_generator(os.environ["FINLLM_MODEL"], os.environ["FINLLM_BASE"])
    return _state["gen"]

class Chat(BaseModel):
    message: str

@app.get("/quote/{symbol}")
def quote(symbol: str):
    return Tools().get_quote(symbol)

@app.post("/chat")
def chat(req: Chat):
    store = _state.get("store")
    agent = Agent(_gen(), Tools(store=store), SYSTEM)
    return agent.run(req.message)

@app.get("/health")
def health():
    return {"ok": True}
