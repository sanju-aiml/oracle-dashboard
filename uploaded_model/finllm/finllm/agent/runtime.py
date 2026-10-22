"""Production agent loop, shaped by 'Measuring Agents in Production' (UC Berkeley, ICML 2026):
 structured bounded workflow (<=10 steps), custom loop (no framework), human approval for anything that moves money,
 confidence routing to a human, LLM-judge + rules as verifier, full audit trail."""
from __future__ import annotations
import json, time
from typing import Callable
from .tools import Tools

MAX_STEPS = 8
EXECUTION_TOOLS = {"place_order", "transfer_funds", "file_return"}      # never auto-run; require approval

class Agent:
    def __init__(self, generate: Callable[[list[dict]], str], tools: Tools, system: str, approve: Callable[[dict], bool] | None = None,
                 min_confidence=0.55, audit_path="audit.jsonl"):
        self.gen, self.tools, self.system = generate, tools, system
        self.approve, self.min_conf, self.audit_path = approve or (lambda c: False), min_confidence, audit_path

    def _audit(self, rec: dict):
        with open(self.audit_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **rec}, default=str, ensure_ascii=False) + "\n")

    def run(self, user: str, context: list[dict] | None = None) -> dict:
        msgs = [{"role": "system", "content": self.system}] + (context or []) + [{"role": "user", "content": user}]
        for step in range(MAX_STEPS):
            out = self.gen(msgs).strip()
            call = self._parse_call(out)
            if call is None:
                verdict = self.verify(out)
                self._audit({"user": user, "final": out, "verdict": verdict, "steps": step})
                if verdict["escalate"]:
                    return {"answer": out, "escalated_to_human": True, "reason": verdict["reason"]}
                return {"answer": out, "escalated_to_human": False}
            if call["tool"] in EXECUTION_TOOLS:
                ok = self.approve(call)
                self._audit({"step": step, "execution_request": call, "approved": ok})
                if not ok:
                    return {"answer": "Action requires human approval and was not approved.", "pending": call, "escalated_to_human": True}
            try:
                res = self.tools.call(call["tool"], call.get("args", {}))
            except Exception as e:
                res = {"error": str(e)}
            self._audit({"step": step, "call": call, "result": res})
            msgs += [{"role": "assistant", "content": out}, {"role": "user", "content": "TOOL_RESULT " + json.dumps(res, default=str, ensure_ascii=False)}]
        return {"answer": "Step budget exhausted; escalating.", "escalated_to_human": True, "reason": "max_steps"}

    @staticmethod
    def _parse_call(text: str):
        try:
            d = json.loads(text)
            return d if isinstance(d, dict) and "tool" in d else None
        except Exception:
            return None

    def verify(self, text: str) -> dict:
        """Rule verifier: guaranteed-return language, missing disclaimer on advice, low confidence -> escalate."""
        low = text.lower()
        banned = ["guaranteed return", "risk-free", "100% profit", "sure shot", "assured return", "cannot lose"]
        for b in banned:
            if b in low:
                return {"escalate": True, "reason": f"prohibited claim: {b}"}
        try:
            d = json.loads(text)
            if isinstance(d, dict) and "confidence" in d and d["confidence"] < self.min_conf and d.get("action") != "abstain":
                return {"escalate": True, "reason": "low confidence"}
        except Exception:
            pass
        return {"escalate": False, "reason": ""}
