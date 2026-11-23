"""FastAPI router to mount in ORACLE's server.py:
    from finllm.bot.api import make_router
    app.include_router(make_router(generate_fn, executor, get_role))
get_role(request)->'demo'|'owner'|... ; replaces the old /api/chat. SSE when ?stream=true."""
import json, time
from collections import defaultdict, deque

def make_router(generate, executor, get_role, audit=None, rate_per_min=20):
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import StreamingResponse
    from pydantic import BaseModel
    from .runtime import BotRuntime, rule_fallback
    r = APIRouter(); hits = defaultdict(deque)
    rt = BotRuntime(generate, executor, fallback=rule_fallback, audit=audit)

    class Chat(BaseModel):
        message: str
        history: list[dict] = []

    def limited(ip):
        q = hits[ip]; now = time.time()
        while q and now - q[0] > 60: q.popleft()
        q.append(now); return len(q) > rate_per_min

    @r.post("/api/chat")
    def chat(p: Chat, request: Request, stream: bool = False):
        if limited(request.client.host if request.client else "?"): raise HTTPException(429, "slow down")
        if len(p.message) > 2000: raise HTTPException(413, "message too long")
        hist = [m for m in p.history[-12:] if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
        role = get_role(request); events = rt.run(p.message, hist, role)
        if stream:
            return StreamingResponse((f"data: {json.dumps(e, ensure_ascii=False, default=str)}\n\n" for e in events), media_type="text/event-stream")
        evs = list(events); fin = evs[-1]
        return {"reply": fin["text"], "mode": fin["mode"], "verified": fin["verified"], "warnings": fin["warnings"], "needs_approval": fin["needs_approval"], "events": evs}

    @r.get("/api/approvals")
    def approvals(request: Request):
        if get_role(request) == "demo": raise HTTPException(403, "login required")
        return list(executor.pending.values())

    @r.post("/api/approvals/{oid}/{action}")
    def decide(oid: str, action: str, request: Request):
        role = get_role(request)
        if role == "demo": raise HTTPException(403, "login required")
        if action == "approve": return executor.approve(oid, approver=role)
        if action == "reject": return executor.reject(oid)
        raise HTTPException(400, "action must be approve or reject")
    return r
