"""Augmented-reality export: a true-scale GLB plus a self-contained AR page.

The AR page uses Google's <model-viewer>: on Android it starts a WebXR session, on iPhone it
hands over to Quick Look (model-viewer builds the USDZ in the browser), and everywhere else it
is an ordinary rotatable viewer. The part is exported in metres, so it appears at real size.
"""
from __future__ import annotations

import base64
import html
import json
import struct
from pathlib import Path

import numpy as np

from print_check import load_stl

SMOOTH_ANGLE_DEG = 35.0      # edges sharper than this stay crisp, gentler ones are shaded smooth
_MAX_GROUP = 64


def _corner_normals(tris: np.ndarray, face_n: np.ndarray) -> np.ndarray:
    """Per-corner normals: average the faces that share a vertex and lie within SMOOTH_ANGLE of this one."""
    n = len(tris)
    flat = np.repeat(face_n, 3, axis=0)
    key = np.round(tris.reshape(-1, 3), 6)
    _, vid = np.unique(key, axis=0, return_inverse=True)
    vid = vid.reshape(-1)
    order = np.argsort(vid, kind="stable")
    sv = vid[order]
    starts = np.flatnonzero(np.r_[True, sv[1:] != sv[:-1]])
    sizes = np.diff(np.r_[starts, len(sv)])
    kmax = int(sizes.max())
    if kmax > _MAX_GROUP:
        return flat
    group = np.repeat(np.arange(len(starts)), sizes)
    slot = np.arange(len(sv)) - np.repeat(starts, sizes)
    pad = np.full((len(starts), kmax), -1, dtype=np.int64)
    pad[group, slot] = order                       # corner indices grouped by vertex
    fn = np.repeat(face_n, 3, axis=0)              # normal of the face each corner belongs to
    out = flat.copy()
    cos_t = np.cos(np.radians(SMOOTH_ANGLE_DEG))
    valid = pad >= 0
    nrm = np.where(valid[..., None], fn[np.where(valid, pad, 0)], 0.0)        # (groups, k, 3)
    dots = np.einsum("gid,gjd->gij", nrm, nrm)                                  # (groups, k, k)
    use = (dots > cos_t) & valid[:, None, :] & valid[:, :, None]
    summed = np.einsum("gij,gjd->gid", use.astype(np.float64), nrm)
    length = np.linalg.norm(summed, axis=2, keepdims=True)
    summed = np.divide(summed, length, out=np.zeros_like(summed), where=length > 1e-12)
    rows = np.flatnonzero(valid)
    gi, ki = np.divmod(rows, kmax)
    out[pad[gi, ki]] = summed[gi, ki]
    return out


def build_glb(stl_path: Path, color=(0.62, 0.66, 0.68)) -> bytes:
    """Binary glTF at real scale (STL is millimetres, glTF is metres), Y-up, resting on the floor."""
    tris = load_stl(stl_path) * 0.001
    p = np.stack([tris[..., 0], tris[..., 2], -tris[..., 1]], axis=-1)            # CAD Z-up -> glTF Y-up
    lo, hi = p.reshape(-1, 3).min(0), p.reshape(-1, 3).max(0)
    p = p - np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])           # centred, base on y = 0
    cr = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(cr, axis=1, keepdims=True)
    keep = ln[:, 0] > 1e-18                                                        # drop degenerate triangles
    p, cr, ln = p[keep], cr[keep], ln[keep]
    face_n = cr / ln
    normals = _corner_normals(p, face_n).astype(np.float32)
    pos = p.reshape(-1, 3).astype(np.float32)
    count = len(pos)
    idx = np.arange(count, dtype=np.uint32)
    pos_b, nrm_b, idx_b = pos.tobytes(), normals.tobytes(), idx.tobytes()
    blob = pos_b + nrm_b + idx_b
    mn, mx = pos.min(0).tolist(), pos.max(0).tolist()
    gltf = {
        "asset": {"version": "2.0", "generator": "Fillet"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": "part"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [*color, 1.0], "metallicFactor": 0.35,
                                                "roughnessFactor": 0.5}, "doubleSided": True}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b), "target": 34962},
                        {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(nrm_b), "target": 34962},
                        {"buffer": 0, "byteOffset": len(pos_b) + len(nrm_b), "byteLength": len(idx_b), "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3", "min": mn, "max": mx},
                      {"bufferView": 1, "componentType": 5126, "count": count, "type": "VEC3"},
                      {"bufferView": 2, "componentType": 5125, "count": count, "type": "SCALAR"}],
    }
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    blob += b"\0" * (-len(blob) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
            + struct.pack("<I4s", len(blob), b"BIN\0") + blob)


AR_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8><title>Fillet AR</title>
<meta name=viewport content="width=device-width,initial-scale=1">
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;600&display=swap">
<script type=module src="https://cdn.jsdelivr.net/npm/@google/model-viewer@3.5.0/dist/model-viewer.min.js"></script>
<style>
 body{margin:0;background:#0E0E0D;color:#EDEBE6;font-family:'Inter Tight',system-ui,sans-serif}
 main{max-width:1000px;margin:auto;padding:24px 16px}
 h1{font-size:1.4rem;font-weight:600;letter-spacing:-.02em;margin:0 0 4px}
 p{color:#8C8880;margin:4px 0 14px;line-height:1.45}
 model-viewer{width:100%;height:68vh;border-radius:14px;border:1px solid #2A2927;
   background:radial-gradient(ellipse at 50% 30%,#1B1B1A 0%,#0B0B0A 80%);--poster-color:transparent}
 #ar{background:#6FA08E;color:#0E0E0D;border:0;border-radius:10px;padding:10px 18px;font:600 14px inherit;
   font-family:inherit;position:absolute;left:50%;transform:translateX(-50%);bottom:16px;cursor:pointer}
 .note{font-size:13px}
</style></head><body><main>
<h1>__TITLE__</h1><p>__PROMPT__</p>
<model-viewer src="data:model/gltf-binary;base64,__GLB__" alt="__TITLE__" camera-controls auto-rotate
  shadow-intensity="1" exposure="1.05" ar ar-modes="webxr scene-viewer quick-look" ar-scale="fixed"
  ar-placement="floor" touch-action="pan-y">
  <button id=ar slot=ar-button>View in your space (AR)</button>
</model-viewer>
<p class=note>__DIMS__ &middot; shown at real size. Open this page on a phone and tap <b>View in your space</b>:
Android uses Chrome (WebXR), iPhone uses Quick Look. On a computer you can still rotate and zoom the model.</p>
</main></body></html>"""


def ar_page(glb: bytes, dims: str, prompt: str) -> str:
    return (AR_PAGE.replace("__GLB__", base64.b64encode(glb).decode())
            .replace("__TITLE__", "Fillet model in AR")
            .replace("__PROMPT__", html.escape(prompt))
            .replace("__DIMS__", html.escape(dims)))
