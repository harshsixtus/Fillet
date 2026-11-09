"""Run all example prompts through the pipeline and report success / retries / bbox error.

    python eval.py                 # run everything, write eval_results.json
    python eval.py --update-readme # also fill the results table in README.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
EXAMPLES = ROOT / "examples" / "examples.json"
README = ROOT / "README.md"
OUT = ROOT / "outputs" / "eval"
DIM_TOL_MM = 1.0   # a model counts as "dims OK" if every bbox side is within this of the request


def bbox_error(actual: list[float], expected: list[float]) -> tuple[float, float]:
    """Compare sorted dimensions (orientation-independent).
    Returns (max abs error in mm, max relative error in %)."""
    a, e = sorted(actual), sorted(expected)
    abs_err = max(abs(x - y) for x, y in zip(a, e))
    rel_err = max(abs(x - y) / y * 100 for x, y in zip(a, e))
    return abs_err, rel_err


def run_example(ex: dict) -> dict:
    from llm import CodeGenerator
    from pipeline import run_pipeline

    t0 = time.time()
    last = None
    attempts = 0
    gen = None
    try:
        gen = CodeGenerator()
        for att in run_pipeline(ex["prompt"], OUT / f"ex{ex['id']}", generator=gen):
            last, attempts = att, attempts + 1
    except Exception as e:  # API errors etc.
        if "429" in str(e) or "RateLimit" in type(e).__name__:
            raise SystemExit(f"Stopped: API rate/quota limit hit ({str(e)[:200]}). "
                             "Wait for the quota to reset or switch LLM_MODEL, then rerun. README not modified.")
        return {**ex, "success": False, "retries": max(attempts - 1, 0),
                "error": f"{type(e).__name__}: {e}", "seconds": round(time.time() - t0, 1)}

    row = {**ex, "success": bool(last and last.ok), "retries": attempts - 1, "models": list(gen.used),
           "seconds": round(time.time() - t0, 1)}
    if last and last.ok:
        m = last.result.metrics
        abs_e, rel_e = bbox_error(m["bbox_mm"], ex["expected_bbox_mm"])
        row.update(actual_bbox_mm=m["bbox_mm"], volume_mm3=m["volume_mm3"],
                   bbox_err_mm=round(abs_e, 3), bbox_err_pct=round(rel_e, 2))
        (OUT / f"ex{ex['id']}" / "final_model.py").write_text(last.code, encoding="utf-8")
    elif last:
        row["error"] = last.result.error.strip().splitlines()[-1] if last.result.error else ""
    return row


def markdown_table(rows: list[dict]) -> str:
    lines = ["| # | Example | Difficulty | Valid | Dims OK | Retries | Requested bbox (mm) | Generated bbox (mm) | Max bbox error |",
             "|---|---------|-----------|-------|---------|---------|---------------------|---------------------|----------------|"]
    for r in rows:
        req = " x ".join(f"{v:g}" for v in r["expected_bbox_mm"])
        if r["success"]:
            act = " x ".join(f"{v:g}" for v in r["actual_bbox_mm"])
            err = f"{r['bbox_err_mm']:g} mm ({r['bbox_err_pct']:g}%)"
        else:
            act, err = "-", "-"
        dims_ok = r["success"] and r["bbox_err_mm"] <= DIM_TOL_MM
        lines.append(f"| {r['id']} | {r['name']} | {r['difficulty']} | {'yes' if r['success'] else 'NO'} | {'yes' if dims_ok else 'NO'} "
                     f"| {r['retries']} | {req} | {act} | {err} |")
    ok = [r for r in rows if r["success"]]
    lines.append("")
    good = [r for r in ok if r["bbox_err_mm"] <= DIM_TOL_MM]
    lines.append(f"**Valid solid: {len(ok)}/{len(rows)} · Dimensions within {DIM_TOL_MM:g} mm: {len(good)}/{len(rows)}** · total retries: {sum(r['retries'] for r in rows)} "
                 f"· mean bbox error (successful): "
                 f"{(sum(r['bbox_err_mm'] for r in ok) / len(ok)) if ok else float('nan'):.3f} mm")
    return "\n".join(lines)


def update_readme(table: str) -> None:
    text = README.read_text(encoding="utf-8")
    new = re.sub(r"(<!-- EVAL:START -->).*?(<!-- EVAL:END -->)",
                 lambda m: f"{m.group(1)}\n{table}\n{m.group(2)}", text, flags=re.DOTALL)
    README.write_text(new, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-readme", action="store_true")
    args = ap.parse_args()

    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    rows = []
    for ex in examples:
        print(f"[{ex['id']}/{len(examples)}] {ex['name']} ...", flush=True)
        row = run_example(ex)
        print(f"    success={row['success']} retries={row['retries']} "
              f"bbox_err={row.get('bbox_err_mm', '-')} mm ({row['seconds']} s)", flush=True)
        rows.append(row)

    table = markdown_table(rows)
    print("\n" + table)
    OUT.mkdir(parents=True, exist_ok=True)
    (ROOT / "eval_results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if args.update_readme:
        update_readme(table)
        print("\nREADME.md updated.")
    return 0 if all(r["success"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
