with open("core.py", "r", encoding="utf-8") as f:
    c = f.read()

c = c.replace("res['total_payment']", "res.get('total_paid', 0)")
c = c.replace('res = finllm_engine.calculate_ca_banking("tax_new_regime", {"income": inc, "deductions": ded})', 'res = finllm_engine.calculate_ca_banking("tax_new_regime", {"income": inc})')

with open("core.py", "w", encoding="utf-8") as f:
    f.write(c)

print("core.py successfully patched!")
