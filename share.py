"""Build shareable artefacts: a ZIP bundle and a standalone HTML viewer."""
from __future__ import annotations

import base64
import io
import json
import zipfile
from datetime import date
from pathlib import Path

import ar
from viewer import standalone_page

README = """Fillet export  ({day})

Prompt:
{prompt}

Measured: bounding box {x:g} x {y:g} x {z:g} mm, volume {vol:,.1f} mm3, valid={valid}

Files
  model.step   - open in FreeCAD / Fusion 360 / SolidWorks / Onshape (editable CAD)
  model.stl    - 3D printing (any slicer)
  model.3mf    - 3D printing (Bambu Studio, PrusaSlicer, Cura; keeps millimetre units)
  model.brep   - OpenCascade native
  model.py     - the CadQuery script that generated it (edit and re-run with `pip install cadquery`)
  view_*.svg   - 2D drawing views
  viewer.html  - double-click to rotate the model in any browser (needs internet for three.js); has an Enter VR button on VR headsets
  model.glb    - true-scale 3D model (metres) for AR/VR apps, Blender, game engines
  ar.html      - open on a phone and tap 'View in your space' to place the part at real size (Android: WebXR, iPhone: Quick Look)
"""


def build_zip(out_dir: Path, prompt: str, metrics: dict, code: str) -> bytes:
    out_dir = Path(out_dir)
    (out_dir / "model.py").write_text(code, encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(list(out_dir.glob("model.*")) + list(out_dir.glob("view_*.svg"))):
            z.write(p, p.name)
        x, y, zz = metrics["bbox_mm"]
        z.writestr("README.txt", README.format(day=date.today().isoformat(), prompt=prompt, x=x, y=y, z=zz,
                                               vol=metrics["volume_mm3"], valid=metrics["is_valid"]))
        z.writestr("prompt.txt", prompt)
        z.writestr("metrics.json", json.dumps(metrics, indent=2))
        z.writestr("viewer.html", build_html(out_dir / "model.stl", prompt, metrics))
        glb = ar.build_glb(out_dir / "model.stl")
        z.writestr("model.glb", glb)
        z.writestr("ar.html", build_ar_html(glb, prompt, metrics))
    return buf.getvalue()


def build_html(stl_path: Path, prompt: str, metrics: dict) -> str:
    x, y, z = metrics["bbox_mm"]
    b64 = base64.b64encode(Path(stl_path).read_bytes()).decode()
    return standalone_page(b64, f"{x:g} × {y:g} × {z:g} mm", prompt, metrics["volume_mm3"])


def build_ar_html(glb: bytes, prompt: str, metrics: dict) -> str:
    x, y, z = metrics["bbox_mm"]
    return ar.ar_page(glb, f"{x:g} × {y:g} × {z:g} mm", prompt)
