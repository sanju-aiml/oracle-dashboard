"""Train + validate everything on ORACLE's own stored data.
   python train.py [SYMBOL ...]  [--images]

Progress is written to gate_log.jsonl (one JSON line per trial and per final gate result).
A symbol passes only if its holdout (the newest 20% of history, never used for choosing settings)
beats the majority baseline with p < 0.02, AUC >= 0.52 and is profitable after trading costs.
Failing is a valid, honest result: the bot then trades nothing for that symbol and ORACLE says so."""
import sys

import config
import image_model
import model
import store


def main(argv):
    do_images = "--images" in argv
    syms = [a for a in argv if not a.startswith("--")] or list(config.ASSETS)
    rows = []
    for s in syms:
        if s not in config.ASSETS:
            print("skip unknown", s)
            continue
        res = model.train(s, "1d", verbose=True)
        rows.append((s, {h: r.get("passed") for h, r in res.items()}))
    passed = sum(1 for _, r in rows for v in r.values() if v)
    total = sum(len(r) for _, r in rows)
    print(f"\nGate passed for {passed} of {total} model(s). Multiple symbols are tested, so a few passes can "
          f"be luck; the live track record in /api/bot/status is the real proof.")
    if do_images:
        rep = image_model.train(syms if len(sys.argv) > 2 else None)
        print("image model:", "PASS" if rep.get("passed") else "FAIL", rep.get("reasons"))


if __name__ == "__main__":
    main(sys.argv[1:])
