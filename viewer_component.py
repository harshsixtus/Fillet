"""Two-way 3D viewer component: shows the STL and returns pen marks drawn on it.

Built as a plain-HTML Streamlit component (no npm build) in components/cad_viewer/.
"""
from __future__ import annotations

import base64
from pathlib import Path

import streamlit.components.v1 as components

_viewer = components.declare_component(
    "cad_viewer", path=str(Path(__file__).parent / "components" / "cad_viewer")
)

FACE_NAMES = {(2, 1): "top (+Z)", (2, -1): "bottom (-Z)", (0, 1): "right (+X)",
              (0, -1): "left (-X)", (1, 1): "back (+Y)", (1, -1): "front (-Y)"}


def cad_viewer(stl_path: Path, model_id: str, dims: str, key: str) -> list[dict]:
    """Render the viewer; returns the list of marks currently drawn on this model."""
    import streamlit as st

    b64 = base64.b64encode(Path(stl_path).read_bytes()).decode()
    prev = st.session_state.get(key) or {}
    saved = prev.get("marks", []) if prev.get("model_id") == model_id else []
    # `marks` lets the viewer redraw its pins if the browser ever reloads the iframe.
    value = _viewer(stl_b64=b64, model_id=model_id, dims=dims, marks=saved, key=key, default=None)
    if not value or value.get("model_id") != model_id:
        return []
    return value.get("marks", [])


def describe_marks(marks: list[dict], bed_offset_z: float = 0.0) -> str:
    """Turn marks into text the LLM can act on (coordinates in the script's frame)."""
    lines = []
    for m in marks:
        x, y, z = m["point"]
        z -= bed_offset_z   # print mode shifts the exported part onto the bed
        nx = m["normal"]
        axis = max(range(3), key=lambda i: abs(nx[i]))
        face = FACE_NAMES[(axis, 1 if nx[axis] >= 0 else -1)]
        shape = {"arrow": "arrow pointing at", "box": "box around", "circle": "circle around",
                 "ellipse": "ellipse around"}.get(m["shape"], "mark at")
        size = f", marked area radius ≈ {m['size_mm']:g} mm" if m.get("size_mm") else ""
        lines.append(f"#{m['n']}: {shape} a spot on the {face} face at X={x:.1f}, Y={y:.1f}, Z={z:.1f} mm{size}")
    return "\n".join(lines)
