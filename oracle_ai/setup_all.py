"""ONE command: seed history -> train price models -> train chart-image model -> self-check -> report.
   python setup_all.py [--skip-seed] [SYMBOL ...]
Run it on your own machine while online. Takes a while the first time (it prints progress).
Writes SETUP_REPORT.md. Honest by design: a model that does not beat chance on unseen data is reported FAIL
and the bot will not trade it; nothing is hidden or tuned until it passes."""
import io
import sys
import time

from PIL import Image, ImageDraw

import config
import image_model
import market_data as md
import model
import store


def _fake_chart_png(up=True, n=40):
    """A clearly drawn green/red candle chart, used only to prove the screenshot reader works."""
    import random
    rnd = random.Random(1)
    W, H = 640, 360
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    p = 100.0
    xs = W // (n + 2)
    for i in range(n):
        o = p
        c = o + rnd.uniform(-1, 1.6 if up else 1) + (0.15 if up else -0.15)
        hi, lo = max(o, c) + rnd.random(), min(o, c) - rnd.random()
        y = lambda v: int(H - (v - 90) * (H / 40))
        col = (0, 160, 80) if c >= o else (210, 40, 40)
        x = xs * (i + 1)
        d.line([(x, y(hi)), (x, y(lo))], fill=col, width=1)
        d.rectangle([x - 4, y(max(o, c)), x + 4, y(min(o, c)) + 1], fill=col)
        p = c
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def main(argv):
    skip_seed = "--skip-seed" in argv
    syms = [a for a in argv if not a.startswith("--")] or list(config.ASSETS)
    t0 = time.time()
    report = []

    print("== 1/4 downloading history into ORACLE's own database ==")
    seeded = {}
    for s in syms:
        if skip_seed:
            seeded[s] = (len(store.load_candles(s, "1d")), "existing")
        else:
            try:
                n, src = md.seed_history(s, "1d", 2000)
            except Exception as e:
                n, src = 0, f"error: {e}"
            seeded[s] = (n, src or "-")
            time.sleep(0.5)
        print(f"  {s:9s} candles={seeded[s][0]:5d} source={seeded[s][1]}")

    print("== 2/4 training + validating price models (holdout gate) ==")
    rows = []
    for s in syms:
        if seeded[s][0] < config.MIN_BARS:
            rows.append((s, "NO DATA", f"only {seeded[s][0]} candles (need {config.MIN_BARS}); check internet and re-run"))
            continue
        try:
            res = model.train(s, "1d", verbose=False)
            for h, r in res.items():
                rows.append((s, "PASS" if r.get("passed") else "FAIL",
                             f"h={h} " + "; ".join(r.get("reasons") or ["edge proven on unseen data"])))
        except Exception as e:
            rows.append((s, "ERROR", str(e)[:120]))
    for r in rows:
        print("  %-9s %-7s %s" % r)

    print("== 3/4 training chart-image model (from ORACLE's own candles) ==")
    try:
        rep = image_model.train(None)
        img_ok = bool(rep.get("passed"))
        img_note = "; ".join(rep.get("reasons") or ["passed on unseen charts"])
    except Exception as e:
        img_ok, img_note = False, f"error: {str(e)[:120]}"
    print(f"  image model: {'PASS' if img_ok else 'FAIL'} - {img_note}")

    print("== 4/4 self-check: can the screenshot reader read a chart? ==")
    read_ok = True
    try:
        out = image_model.analyze_image(_fake_chart_png(True))
        read_ok = bool(out.get("ok"))
        print("  chart reader:", "OK" if read_ok else f"FAIL - {out.get('reason')}",
              f"(p_up={out.get('p_up'):.2f}, validated={out.get('validated')})" if read_ok else "")
    except Exception as e:
        read_ok = False
        print("  chart reader: ERROR", e)

    passed = sum(1 for r in rows if r[1] == "PASS")
    lines = ["# ORACLE setup report", f"_{time.strftime('%Y-%m-%d %H:%M')} - {time.time() - t0:.0f}s_", "",
             "| Symbol | Result | Detail |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    lines += ["", f"Price models passed: {passed} of {len(rows)}",
              f"Image model: {'PASS' if img_ok else 'FAIL'} - {img_note}",
              f"Chart reader works: {read_ok}", "",
              "A FAIL means no proven edge on unseen data. ORACLE then answers with facts and states that, and the bot does not trade it."]
    open("SETUP_REPORT.md", "w", encoding="utf-8").write("\n".join(lines))
    print(f"\nDone. {passed} price model(s) passed. Report saved to SETUP_REPORT.md. Send that file to Claude.")


if __name__ == "__main__":
    main(sys.argv[1:])
