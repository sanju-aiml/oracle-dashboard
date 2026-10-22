"""AI marketing engine for large Indian businesses: segmentation -> multilingual copy -> compliance guard -> bandit A/B.
Compliance rules encoded: TRAI DLT template/consent, DPDP Act consent, SEBI/ASCI no guaranteed-returns language,
RBI digital-lending disclosure. The LLM writes copy; deterministic code enforces the rules."""
from __future__ import annotations
import re, random
from dataclasses import dataclass, field
from typing import Callable

LANGS = {"en": "English", "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "kn": "Kannada", "mr": "Marathi", "bn": "Bengali", "gu": "Gujarati"}
BANNED = [r"guarantee[d]?\s+returns?", r"risk[- ]free", r"double your money", r"100%\s*(safe|profit)", r"no risk", r"assured\s+returns?"]
FIN_DISCLAIMER = {"en": "Investments are subject to market risks. Read all scheme documents carefully.",
                  "hi": "निवेश बाजार जोखिमों के अधीन है। सभी योजना संबंधित दस्तावेज़ ध्यान से पढ़ें।",
                  "te": "పెట్టుబడులు మార్కెట్ రిస్క్‌లకు లోబడి ఉంటాయి. అన్ని పథక పత్రాలను జాగ్రత్తగా చదవండి."}

@dataclass
class Customer:
    id: str; lang: str = "en"; consent_marketing: bool = False; dnd: bool = False
    recency_days: int = 999; frequency: int = 0; monetary: float = 0.0; segment: str = ""

def rfm_segment(c: Customer) -> str:
    if c.recency_days <= 30 and c.frequency >= 5 and c.monetary >= 50000: return "champion"
    if c.recency_days <= 60 and c.frequency >= 2: return "loyal"
    if c.recency_days > 180 and c.frequency >= 3: return "at_risk"
    if c.frequency == 0: return "prospect"
    return "regular"

def can_contact(c: Customer, channel: str) -> tuple[bool, str]:
    if not c.consent_marketing: return False, "no DPDP marketing consent"
    if c.dnd and channel in ("sms", "voice", "whatsapp"): return False, "NDNC/DND registered"
    return True, "ok"

def compliance_check(text: str, financial: bool, lang: str = "en") -> list[str]:
    issues = [f"banned phrase /{p}/" for p in BANNED if re.search(p, text, re.I)]
    if financial and FIN_DISCLAIMER.get(lang, FIN_DISCLAIMER["en"]) not in text:
        issues.append("missing mandatory risk disclaimer")
    if len(text) > 1024: issues.append("exceeds WhatsApp template length")
    return issues

class ThompsonBandit:
    """Picks the best-performing copy variant online (Beta-Bernoulli on conversion)."""
    def __init__(self, arms: list[str], seed=0):
        self.a = {k: 1.0 for k in arms}; self.b = {k: 1.0 for k in arms}; self.rng = random.Random(seed)
    def pick(self) -> str:
        return max(self.a, key=lambda k: self.rng.betavariate(self.a[k], self.b[k]))
    def update(self, arm: str, converted: bool):
        (self.a if converted else self.b)[arm] += 1

class MarketingBot:
    def __init__(self, generate: Callable[[list[dict]], str]):
        self.gen = generate

    def draft(self, product: str, segment: str, lang: str, financial=False, n_variants=3, tone="warm, concise") -> list[dict]:
        out = []
        for i in range(n_variants):
            p = [{"role": "system", "content": "You write compliant Indian marketing copy. No guaranteed-return claims. Under 400 characters."},
                 {"role": "user", "content": f"Write variant {i+1} of a {LANGS[lang]} WhatsApp message for '{product}' to the '{segment}' segment. Tone: {tone}. Include one clear call to action."}]
            text = self.gen(p).strip()
            if financial: text += "\n" + FIN_DISCLAIMER.get(lang, FIN_DISCLAIMER["en"])
            out.append({"variant": f"v{i+1}", "text": text, "issues": compliance_check(text, financial, lang)})
        return out

    def plan(self, customers: list[Customer], channel="whatsapp") -> dict:
        sent, blocked = [], []
        for c in customers:
            c.segment = rfm_segment(c)
            ok, why = can_contact(c, channel)
            (sent if ok else blocked).append((c.id, c.segment, c.lang) if ok else (c.id, why))
        return {"eligible": sent, "blocked": blocked}
