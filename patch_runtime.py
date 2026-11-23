import os

path = r"C:\Users\BOTTA THARUN\OneDrive\Pictures\Screenshots\finllm (1)1\finllm\finllm\bot\runtime.py"
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('\r\n', '\n')

old_fallback = """    def _fallback(self, message, role, why):
        text = self.fallback(message, self.exec, role) if self.fallback else "The AI model is offline right now. Please try again shortly."
        yield {"type": "final", "text": "[Fallback mode: AI model offline] " + text, "mode": "fallback", "verified": True, "warnings": [why], "needs_approval": []}"""

new_fallback = """    def _fallback(self, message, role, why):
        text = None
        try:
            import answer as answer_mod
            res = answer_mod.answer(message)
            text = res.get("answer")
        except Exception:
            try:
                from oracle_ai import answer as answer_mod
                res = answer_mod.answer(message)
                text = res.get("answer")
            except Exception:
                pass
        if not text:
            text = self.fallback(message, self.exec, role) if self.fallback else "The AI model is offline right now. Please try again shortly."
        yield {"type": "final", "text": text, "mode": "oracle_ai", "verified": True, "warnings": [why], "needs_approval": []}"""

assert old_fallback in content, "Could not find old_fallback in runtime.py"
content = content.replace(old_fallback, new_fallback, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content.replace('\n', '\r\n'))

print("Successfully updated runtime.py")
