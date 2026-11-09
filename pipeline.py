"""Prompt -> LLM -> code -> sandbox -> CAD, with self-repair and a geometry self-check."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from llm import CodeGenerator
from sandbox import SandboxResult, prewarm, run_code
from verify import geometry_proven

MAX_REPAIRS = 3   # total extra LLM rounds after the first generation
MAX_REVIEWS = 2   # visual design-review rounds per build (each may trigger one revision)


@dataclass
class Attempt:
    index: int              # 0 = first generation, 1.. = revisions
    code: str
    result: SandboxResult
    note: str = ""          # why this attempt led to another one
    accepted: bool = False  # True on the attempt that is the final answer
    best_effort: bool = False  # accepted although it did not pass every check (best valid attempt)

    @property
    def ok(self) -> bool:
        return self.result.ok


def _render(res: SandboxResult) -> bytes | None:
    """Three-view PNG of a built part for the design review (coarse mesh when available). None on failure."""
    try:
        from render import render_views_png
        coarse = res.stl_path.with_name(res.stl_path.stem + "_render.stl")
        return render_views_png(coarse if coarse.exists() else res.stl_path)
    except Exception:  # noqa: BLE001 - the review is optional
        return None


def run_pipeline(prompt: str, work_dir: Path | None = None,
                 generator: CodeGenerator | None = None,
                 max_repairs: int = MAX_REPAIRS, self_check: bool = True,
                 print_mode: bool = False, current_code: str | None = None,
                 marks: str = "", tick=None) -> Iterator[Attempt]:
    """Yield each attempt as soon as it finishes. A revision is triggered either
    by a sandbox failure (traceback sent back) or by the LLM's own comparison of
    the measured geometry with the request. Stops on acceptance or after
    1 + max_repairs attempts."""
    work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="text2cad_"))
    gen = generator or CodeGenerator()

    prewarm()   # CadQuery imports in the background while the LLM writes the code
    # First message builds from scratch; a follow-up (current_code given) edits the existing model.
    code = gen.revise(prompt, current_code, marks) if current_code else gen.generate(prompt)
    best: Attempt | None = None   # best valid model so far: fewest separate pieces, then the latest
    reviews = 0
    for i in range(max_repairs + 1):
        res = run_code(code, work_dir / f"attempt_{i}", print_mode=print_mode, tick=tick)
        last = i == max_repairs
        if res.ok and (best is None or res.metrics.get("num_solids", 1) <= best.result.metrics.get("num_solids", 1)):
            best = Attempt(i, code, res)
        if res.ok and res.metrics.get("num_solids", 1) > 1 and not last:
            # Loose pieces are almost never intended: ask for one joined solid before anything else.
            n = res.metrics["num_solids"]
            yield Attempt(i, code, res, note=f"{n} separate solids; asking for one joined solid")
            code = gen.repair(
                f"The script ran, but the result consists of {n} separate, disconnected solids instead of one part. "
                "Make it ONE solid: features must overlap or touch the main body (no gaps), then union them. "
                "Check positions: a feature placed on a face must start exactly at that face."
            )
            continue
        if res.ok:
            # Skip the (slow) LLM self-check when the measurements provably match what the user asked for.
            proven = geometry_proven(getattr(gen, "requests", []), res.metrics)
            fixed = None
            if self_check and not last and not proven:
                # Visual design review: a vision model looks at rendered views of the part (shape, proportions,
                # recognisable features). Falls back to the text-only self-check if no vision model is reachable.
                verdict, fixes = ("unavailable", "")
                if reviews < MAX_REVIEWS and hasattr(gen, "review"):
                    png = _render(res)
                    if png:
                        verdict, fixes = gen.review(png, res.metrics)
                if verdict == "fix":
                    reviews += 1
                    yield Attempt(i, code, res, note=f"Design review: {fixes}")
                    code = gen.revise_from_review(fixes)
                    continue
                if verdict == "unavailable":
                    fixed = gen.check(res.metrics)
            if fixed is None:
                yield Attempt(i, code, res, accepted=True, best_effort=res.metrics.get("num_solids", 1) > 1)
                return
            yield Attempt(i, code, res, note="Self-check: measured geometry does not match the request; revising")
            code = fixed
        else:
            if last and best is not None:
                # Never end with nothing: hand back the best valid model as a draft to refine in the chat.
                yield Attempt(i, code, res, note="Execution failed")
                yield Attempt(best.index, best.code, best.result, accepted=True, best_effort=True)
                return
            yield Attempt(i, code, res, accepted=last, note="" if last else "Execution failed; sending traceback back")
            if last:
                return
            code = gen.repair(res.error, attempt=i + 1)
