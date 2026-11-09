"""Run LLM-generated CadQuery code in a separate, time-limited subprocess.

The parent process never calls exec() on generated code. A child interpreter (`python -I sandbox.py --worker`)
executes it with a restricted builtins table and an import hook that only allows `cadquery`, `math` and `t2c`,
and it never sees API keys (its environment is filtered).

Speed without weaker isolation:
- Every build still runs in its own, fresh process, and that process exits after its one job.
- Importing CadQuery takes several seconds, so a worker is *pre-warmed*: started while the LLM is still writing
  code, it imports everything and then waits for its single job on stdin. The time limit starts with the job.
- The worker reports metrics + the preview files (STEP, STL) first, then finishes the slower extras
  (3MF, BREP, dimensioned drawings) in the background; `wait_exports()` waits for them when they are needed.

NOTE: this gives process isolation, a hard timeout and a minimal namespace.
It is not a hardened security boundary against a determined attacker.
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

TIMEOUT_S = 20            # for the model code + checks + preview export (after the worker has started the job)
STARTUP_LIMIT_S = 90      # a cold worker must finish importing CadQuery within this
EXPORT_LIMIT_S = 90       # background extras (3MF, BREP, drawings) are stopped after this
ALLOWED_MODULES = {"cadquery", "math", "t2c"}   # t2c = our robust helper toolkit
HERE = Path(__file__).resolve()


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
        return {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME")}


def _server_mode() -> bool:
    try:
        import config
        return bool(config.SERVER_MODE)
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Parent side: worker pool of (at most) one pre-warmed spare
# --------------------------------------------------------------------------- #
@dataclass
class _Worker:
    proc: subprocess.Popen
    log: Path

    def alive(self) -> bool:
        return self.proc.poll() is None


_spare: _Worker | None = None
_finishing: list[_Worker] = []   # workers that already returned a result and are writing the extras


def _spawn() -> _Worker:
    fd, log = tempfile.mkstemp(prefix="fillet_worker_", suffix=".log")
    os.close(fd)
    proc = subprocess.Popen(
        [sys.executable, "-I", str(HERE), "--worker"],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=open(log, "w"),  # noqa: SIM115
        cwd=tempfile.gettempdir(), env=_sandbox_env(), text=True,
    )
    return _Worker(proc, Path(log))


def _kill(w: _Worker) -> None:
    if not w.alive():
        return
    if os.name == "nt":   # a venv's python.exe is a launcher: kill the whole process tree
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(w.proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        w.proc.kill()


def _reap() -> None:
    _finishing[:] = [w for w in _finishing if w.alive()]


def prewarm() -> None:
    """Start a worker in the background so CadQuery is already imported when the code arrives."""
    global _spare
    _reap()
    if _spare is not None and _spare.alive():
        return
    if _server_mode() and _finishing:
        return   # small server: don't hold a second CadQuery process in memory while one is still exporting
    _spare = _spawn()


@atexit.register
def _shutdown() -> None:
    for w in ([_spare] if _spare else []) + _finishing:
        _kill(w)


def run_code(code: str, out_dir: Path, timeout: int = TIMEOUT_S, print_mode: bool = False) -> SandboxResult:
    global _spare
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    code_file = out_dir / "model.py"
    code_file.write_text(code, encoding="utf-8")
    result_file, started, done = out_dir / "result.json", out_dir / "started", out_dir / "exports.done"
    for p in (result_file, started, done):
        p.unlink(missing_ok=True)

    _reap()
    w = _spare if (_spare is not None and _spare.alive()) else _spawn()
    _spare = None
    try:
        w.proc.stdin.write(json.dumps({"code": str(code_file), "out_dir": str(out_dir), "result": str(result_file),
                                       "print_mode": bool(print_mode)}) + "\n")
        w.proc.stdin.close()
    except OSError:
        pass

    t0, t_job = time.time(), None
    while True:
        if result_file.exists():
            break
        if t_job is None and started.exists():
            t_job = time.time()
        if not w.alive() and not result_file.exists():
            time.sleep(0.05)   # the worker may have written the file just before exiting
            if not result_file.exists():
                break
        if (t_job is not None and time.time() - t_job > timeout) or (t_job is None and time.time() - t0 > STARTUP_LIMIT_S):
            _kill(w)
            prewarm()
            return SandboxResult(False, f"TimeoutError: code did not finish within {timeout} s "
                                        "(simplify the geometry / avoid heavy booleans or huge loops)")
        time.sleep(0.03)

    if result_file.exists():
        data = json.loads(result_file.read_text(encoding="utf-8"))
        if w.alive():
            _finishing.append(w)      # still writing 3MF / BREP / drawings
        prewarm()                     # get the next worker ready (e.g. for a repair attempt)
        if data["ok"]:
            return SandboxResult(True, "", data["metrics"], Path(data["step"]), Path(data["stl"]))
        return SandboxResult(False, data["error"])

    # Worker died without writing a result (segfault in OCC, import failure...)
    prewarm()
    tail = ""
    try:
        tail = w.log.read_text(encoding="utf-8", errors="replace").strip()[-3000:]
    except OSError:
        pass
    return SandboxResult(False, f"Process exited with code {w.proc.returncode}.\n{tail}")


def wait_exports(out_dir: Path, timeout: float = EXPORT_LIMIT_S) -> bool:
    """Wait until the background extras (3MF, BREP, drawings) of a build are written. True when complete."""
    out_dir = Path(out_dir)
    if not (out_dir / "result.json").exists() or (out_dir / "exports.done").exists():
        return True   # nothing pending (e.g. a library model, or an older build that exported everything)
    if not (out_dir / "started").exists():
        return True
    end = time.time() + timeout
    while time.time() < end:
        if (out_dir / "exports.done").exists():
            return True
        _reap()
        if not _finishing:
            # no worker is exporting any more (e.g. it was stopped, or the app restarted): what exists is final
            return (out_dir / "exports.done").exists()
        time.sleep(0.1)
    return False


# --------------------------------------------------------------------------- #
# Worker side
# --------------------------------------------------------------------------- #
def _worker() -> None:
    import builtins
    import math
    import traceback

    import cadquery as cq   # the slow import happens here, before the job arrives

    sys.path.insert(0, str(HERE.parent))
    import cad_export
    import t2c

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level != 0 or name.split(".")[0] not in ALLOWED_MODULES:
            raise ImportError(f"import of '{name}' is not allowed; only cadquery, math and t2c")
        return real_import(name, globals, locals, fromlist, level)

    safe_names = (
        "abs all any bool dict divmod enumerate filter float int isinstance len list map "
        "max min pow print range reversed round set sorted str sum tuple zip complex "
        "True False None Exception ValueError TypeError ArithmeticError ZeroDivisionError "
        "StopIteration slice"
    ).split()
    safe_builtins = {n: getattr(builtins, n) for n in safe_names if hasattr(builtins, n)}
    safe_builtins["__import__"] = guarded_import

    line = sys.stdin.readline()          # wait for exactly one job
    if not line.strip():
        return
    job = json.loads(line)
    out_dir = Path(job["out_dir"])
    (out_dir / "started").write_text("1")

    def write(obj: dict) -> None:        # atomic, so the parent never reads a half-written file
        tmp = Path(job["result"] + ".tmp")
        tmp.write_text(json.dumps(obj), encoding="utf-8")
        os.replace(tmp, job["result"])

    try:
        ns = {"__builtins__": safe_builtins, "cq": cq, "cadquery": cq, "math": math, "h": t2c, "t2c": t2c}
        source = Path(job["code"]).read_text(encoding="utf-8-sig")
        exec(compile(source, "<generated>", "exec"), ns)  # noqa: S102 - isolated child process

        if "result" not in ns:
            raise cad_export.InvalidResult("Code did not define a variable named `result`")
        shape = cad_export.to_shape(ns["result"])
        metrics = cad_export.compute_metrics(shape)
        metrics["bed_offset_z"] = round(-shape.BoundingBox().zmin, 4) if job["print_mode"] else 0.0
        shape, step, stl = cad_export.export_preview(shape, out_dir, print_mode=job["print_mode"])
    except BaseException:  # noqa: BLE001 - report everything back to the LLM
        write({"ok": False, "error": traceback.format_exc()[-3000:]})
        return
    write({"ok": True, "metrics": metrics, "step": str(step), "stl": str(stl)})

    # the result is already delivered; the extras follow in the background
    try:
        cad_export.export_rest(shape, out_dir)
    finally:
        (out_dir / "exports.done").write_text("1")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--worker":
        _worker()
