"""Local model library: save, list, reopen and delete generated models.

Each model lives in library/<id>/ with its CAD files and a meta.json that also
stores the chat and LLM conversation, so a reopened model can keep being edited.
"""
from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path

LIB = Path(__file__).parent / "library"
FILES = ("model.step", "model.stl", "model.3mf", "model.brep", "model.py",
         "view_iso.svg", "view_top.svg", "view_front.svg", "view_side.svg")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "model"


def save(final: dict, name: str, chat: list[dict], llm_messages: list[dict], model_id: str | None = None) -> str:
    """Create or overwrite a library entry. Returns its id."""
    model_id = model_id or f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(name)}-{uuid.uuid4().hex[:4]}"
    dest = LIB / model_id
    dest.mkdir(parents=True, exist_ok=True)
    src = Path(final["out_dir"])
    try:
        import sandbox
        sandbox.wait_exports(src)   # drawings / 3MF may still be finishing in the background
    except Exception:  # noqa: BLE001
        pass
    (src / "model.py").write_text(final["code"], encoding="utf-8")
    for f in FILES:
        if (src / f).exists():
            shutil.copy2(src / f, dest / f)
    meta_path = dest / "meta.json"
    created = json.loads(meta_path.read_text(encoding="utf-8"))["created"] if meta_path.exists() else time.time()
    meta = {
        "id": model_id, "name": name, "created": created, "updated": time.time(),
        "prompt": final.get("prompt", ""), "metrics": final["metrics"], "models": final.get("models", []),
        "print_mode": final.get("print_mode", False), "chat": chat, "llm_messages": llm_messages,
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return model_id


def list_models() -> list[dict]:
    if not LIB.exists():
        return []
    items = []
    for d in LIB.iterdir():
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            meta["dir"] = str(d)
            items.append(meta)
        except (OSError, ValueError, KeyError):
            continue
    return sorted(items, key=lambda m: m.get("updated", 0), reverse=True)


def load(model_id: str) -> dict:
    """Return everything the app needs to reopen the model in the workspace."""
    d = LIB / model_id
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    final = {
        "code": (d / "model.py").read_text(encoding="utf-8"), "metrics": meta["metrics"],
        "attempts": 0, "step": (d / "model.step").read_bytes(), "stl_path": str(d / "model.stl"),
        "out_dir": str(d), "prompt": meta.get("prompt", ""), "print_mode": meta.get("print_mode", False),
        "models": meta.get("models", []),
    }
    return {"final": final, "chat": meta.get("chat", []), "llm_messages": meta.get("llm_messages", []),
            "name": meta["name"], "id": model_id}


def delete(model_id: str) -> None:
    d = (LIB / model_id).resolve()
    if d.parent == LIB.resolve() and d.exists():
        shutil.rmtree(d)
