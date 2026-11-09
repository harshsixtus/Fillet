"""Run LLM-generated CadQuery code in a separate, time-limited subprocess.

The parent process never calls exec() on generated code. A child interpreter
(`python -I sandbox.py --child ...`) executes it with a restricted builtins
table and an import hook that only allows `cadquery` and `math`.

NOTE: this gives process isolation, a hard timeout and a minimal namespace.
It is not a hardened security boundary against a determined attacker.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

TIMEOUT_S = 20
MARKER = "@@RESULT@@"
ALLOWED_MODULES = {"cadquery", "math", "t2c"}   # t2c = our robust helper toolkit


@dataclass
class SandboxResult:
    ok: bool
    error: str = ""
    metrics: dict = field(default_factory=dict)
    step_path: Path | None = None
    stl_path: Path | None = None


def _sandbox_env() -> dict:
    try:
        from config import sandbox_env
        return sandbox_env()
    except Exception:  # noqa: BLE001 - fall back to a minimal safe environment
        import os
        return {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")}


# --------------------------------------------------------------------------- #
# Parent side
# --------------------------------------------------------------------------- #
def run_code(code: str, out_dir: Path, timeout: int = TIMEOUT_S, print_mode: bool = False) -> SandboxResult:
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    code_file = out_dir / "model.py"
    code_file.write_text(code, encoding="utf-8")
    result_file = out_dir / "result.json"
    result_file.unlink(missing_ok=True)

    cmd = [sys.executable, "-I", str(Path(__file__).resolve()), "--child",
           str(code_file), str(out_dir), str(result_file), "1" if print_mode else "0"]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL, cwd=tempfile.gettempdir(),
            env=_sandbox_env(),   # no API keys or other secrets for generated code
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(False, f"TimeoutError: code did not finish within {timeout} s "
                                    "(simplify the geometry / avoid heavy booleans or huge loops)")

    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        if data["ok"]:
            return SandboxResult(True, "", data["metrics"],
                                 Path(data["step"]), Path(data["stl"]))
        return SandboxResult(False, data["error"])

    # Child died without writing a result (segfault in OCC, syntax at import...)
    tail = (proc.stderr or proc.stdout or "").strip()[-3000:]
    return SandboxResult(False, f"Process exited with code {proc.returncode}.\n{tail}")


# --------------------------------------------------------------------------- #
# Child side
# --------------------------------------------------------------------------- #
def _child(code_path: str, out_dir: str, result_path: str, print_mode: str = "0") -> None:
    import builtins
    import traceback

    def write(obj: dict) -> None:
        Path(result_path).write_text(json.dumps(obj), encoding="utf-8")

    try:
        import math

        import cadquery as cq

        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import cad_export

        real_import = builtins.__import__

        def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
            if level != 0 or name.split(".")[0] not in ALLOWED_MODULES:
                raise ImportError(f"import of '{name}' is not allowed; only cadquery and math")
            return real_import(name, globals, locals, fromlist, level)

        safe_names = (
            "abs all any bool dict divmod enumerate filter float int isinstance len list map "
            "max min pow print range reversed round set sorted str sum tuple zip complex "
            "True False None Exception ValueError TypeError ArithmeticError ZeroDivisionError "
            "StopIteration slice"
        ).split()
        safe_builtins = {n: getattr(builtins, n) for n in safe_names if hasattr(builtins, n)}
        safe_builtins["__import__"] = guarded_import

        import t2c
        ns = {"__builtins__": safe_builtins, "cq": cq, "cadquery": cq, "math": math, "h": t2c, "t2c": t2c}
        source = Path(code_path).read_text(encoding="utf-8-sig")
        exec(compile(source, "<generated>", "exec"), ns)  # noqa: S102 - isolated child process

        if "result" not in ns:
            raise cad_export.InvalidResult("Code did not define a variable named `result`")
        shape = cad_export.to_shape(ns["result"])
        metrics = cad_export.compute_metrics(shape)
        metrics["bed_offset_z"] = round(-shape.BoundingBox().zmin, 4) if print_mode == "1" else 0.0
        step, stl = cad_export.export_files(shape, Path(out_dir), print_mode=print_mode == "1")
        write({"ok": True, "metrics": metrics, "step": str(step), "stl": str(stl)})
    except BaseException:  # noqa: BLE001 - report everything back to the LLM
        tb = traceback.format_exc()
        write({"ok": False, "error": tb[-3000:]})


if __name__ == "__main__":
    if len(sys.argv) == 6 and sys.argv[1] == "--child":
        _child(*sys.argv[2:])
