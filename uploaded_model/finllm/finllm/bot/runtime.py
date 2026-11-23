"""Production agent loop for the ORACLE bot. Bounded steps, schema-validated tool calls, tool timeouts, untrusted-data wrapping,
number-grounding verifier, banned-claim filter, deterministic fallback when the model is offline, full audit trail."""
from __future__ import annotations
import json, re, time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
from typing import Callable, Iterator
from . import spec
from .eval_bot import ungrounded

BANNED = ["guaranteed return", "risk-free", "sure shot", "assured return", "100% profit", "cannot lose"]
_POOL = ThreadPoolExecutor(max_workers=4)

def _with_timeout(fn, timeout, *a, **k):
    f = _POOL.submit(fn, *a, **k)
    try: return f.result(timeout=timeout)
    except FTimeout: raise TimeoutError(f"timeout after {timeout}s")

class BotRuntime:
    def __init__(self, generate: Callable[[list[dict]], str], executor: Callable, fallback: Callable | None = None, max_steps=6,
                 gen_timeout=60, tool_timeout=10, audit: Callable[[dict], None] | None = None, system: str = spec.SYSTEM_BOT):
        self.gen, self.exec, self.fallback = generate, executor, fallback
        self.max_steps, self.gen_t, self.tool_t, self.audit, self.system = max_steps, gen_timeout, tool_timeout, audit or (lambda r: None), system

    def run(self, message: str, history: list[dict] | None = None, role: str = "demo") -> Iterator[dict]:
        msgs = [{"role": "system", "content": self.system}] + (history or []) + [{"role": "user", "content": message}]
        results, calls, errors = [], 0, 0
        for step in range(self.max_steps):
            try:
                out = _with_timeout(self.gen, self.gen_t, msgs).strip()
            except Exception as e:
                self.audit({"event": "model_error", "error": str(e)})
                yield from self._fallback(message, role, str(e)); return
            call = spec.parse_call(out)
            if call is None:
                yield self._final(out, results, step, message, role); return
            ok, err = spec.validate_call(call)
            if not ok:
                errors += 1; self.audit({"event": "invalid_call", "call": call, "error": err})
                if errors > 2: yield from self._fallback(message, role, "invalid tool calls"); return
                msgs += [{"role": "assistant", "content": out}, {"role": "user", "content": f"TOOL_ERROR {err}. Reply with a valid tool call."}]; continue
            calls += 1
            if calls > 4: yield from self._fallback(message, role, "too many tool calls"); return
            yield {"type": "tool_call", "tool": call["tool"], "args": call.get("args", {})}
            try: res = _with_timeout(self.exec, self.tool_t, call["tool"], call.get("args", {}), role)
            except Exception as e: res = {"status": "unavailable", "error": str(e)[:120]}
            results.append(res); self.audit({"event": "tool", "call": call, "result": res, "role": role})
            yield {"type": "tool_result", "result": res}
            msgs += [{"role": "assistant", "content": out}, {"role": "user", "content": spec.wrap_result(res)}]
        yield from self._fallback(message, role, "step budget exhausted")

    def _final(self, text, results, step, message, role="demo"):
        warns = []
        low = text.lower()
        if any(b in low for b in BANNED):
            text = "I can't make guarantees about returns. I can share live data, model probabilities and risk instead."; warns.append("blocked prohibited claim")

        # Check if this is an investment / stock inquiry
        is_invest = any(w in message.lower() for w in ["invest", "investment", "buy", "sell", "shares", "stock", "portfolio"]) or any(
            isinstance(r, dict) and (r.get("kind") in ("forecast", "quote") or "price" in r) for r in results
        )
        if is_invest:
            # 1. Neutralize direct buy/sell commands or guaranteed advice
            text = re.sub(r"(?i)\byou should (consider )?(investing|invest|buy)\b", "investors may evaluate", text)
            text = re.sub(r"(?i)\byou should sell\b", "investors may evaluate selling", text)
            text = re.sub(r"(?i)\bi recommend (buying|investing|purchasing)\b", "market data indicates consideration of", text)
            text = re.sub(r"(?i)\bi suggest (buying|investing|purchasing)\b", "market data indicates consideration of", text)
            text = re.sub(r"(?i)\bi advise (you to |)(buy|invest)\b", "investors should review", text)

            # 2. Ensure live market feed data is present
            quote = next((r for r in results if isinstance(r, dict) and "price" in r and "source" in r), None)
            if not quote:
                # determine symbol from results or message
                sym = None
                for r in results:
                    if isinstance(r, dict) and ("symbol" in r or "clean_symbol" in r):
                        sym = r.get("clean_symbol") or r.get("symbol")
                        break
                if not sym:
                    m_low = message.lower()
                    if "amazon" in m_low or "amzn" in m_low: sym = "AMZN"
                    elif "apple" in m_low or "aapl" in m_low: sym = "AAPL"
                    elif "reliance" in m_low: sym = "RELIANCE"
                    elif "tcs" in m_low: sym = "TCS"
                if sym:
                    try:
                        q_res = self.exec("get_quote", {"symbol": sym}, role)
                        if isinstance(q_res, dict) and q_res.get("price") is not None:
                            results.insert(0, q_res)
                            quote = q_res
                    except Exception:
                        pass

            if quote and quote.get("price") is not None:
                q_sym = quote.get("symbol", "")
                q_prc = quote.get("price")
                q_chg = quote.get("change_pct", 0.0)
                q_src = quote.get("source", "Live Market Feed")
                q_stat = quote.get("status", "live")
                q_ts = quote.get("ts", "")
                feed_line = f"Live Market Feed ({q_sym}): Price ${q_prc:,.2f} ({q_chg:+,.2f}%), Source: {q_src}, Status: {q_stat} as of {q_ts}.\n\n"
                if str(q_prc) not in text:
                    text = feed_line + text

            # 3. Ensure key risks are present
            if "risk" not in text.lower():
                text += "\n\nKey risks: Market volatility, macroeconomic fluctuations, competitive headwinds, and statistical forecast uncertainty."

            # 4. Mandatory educational disclaimer
            disclaimer = "Educational purpose only, not financial advice."
            if disclaimer not in text:
                text = text.rstrip() + f"\n\n{disclaimer}"

        ctx = " ".join(json.dumps(r, ensure_ascii=False) for r in results) + " " + message
        bad = ungrounded(text, ctx)
        if bad: warns.append(f"unverified figures: {bad[:5]}")
        pend = [r for r in results if isinstance(r, dict) and r.get("status") == "pending_approval"]
        self.audit({"event": "final", "text": text, "warnings": warns, "steps": step})
        return {"type": "final", "text": text, "mode": "ai", "verified": not warns, "warnings": warns, "needs_approval": pend}

    def _fallback(self, message, role, why):
        text = self.fallback(message, self.exec, role) if self.fallback else "The AI model is offline right now. Please try again shortly."
        yield {"type": "final", "text": "[Fallback mode: AI model offline] " + text, "mode": "fallback", "verified": True, "warnings": [why], "needs_approval": []}

def rule_fallback(message: str, executor: Callable, role: str) -> str:
    """Deterministic, tool-backed answers for the most common questions when the model is down. English only, no free-form generation."""
    m = message.lower(); nums = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", m)]
    try:
        if "gst" in m and len(nums) >= 2:
            r = executor("calc", {"kind": "gst", "params": {"amount": nums[0], "rate_pct": nums[1]}}, role)
            return f"GST = ₹{r['gst']:,.2f}; total payable ₹{r['total']:,.2f}."
        if "emi" in m and len(nums) >= 3:
            r = executor("calc", {"kind": "emi", "params": {"P": nums[0], "annual_pct": nums[1], "years": nums[2]}}, role)
            return f"Monthly EMI ₹{r['emi']:,.2f}; total interest ₹{r['total_interest']:,.2f}."
        from .dataset import STOCKS
        for sym, _, names in STOCKS:
            if names["en"].lower() in m or sym.lower() in m:
                r = executor("get_quote", {"symbol": sym}, role)
                if r.get("status") == "unavailable": return f"{names['en']} data is unavailable right now."
                return f"{names['en']}: {r['price']:,.2f} ({r['change_pct']:+.2f}%), source {r['source']}, {r['ts']}, status {r['status']}."
    except Exception as e:
        return f"Could not fetch data ({e})."
    return "The AI model is offline and I can only answer GST, EMI and price questions right now."
