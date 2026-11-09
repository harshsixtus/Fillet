"""Tiny software renderer: STL -> shaded PNG with three views (isometric, front, top).

Used so a vision model can *look* at the generated part and review its shape. Pure numpy + zlib (no GPU,
no extra dependencies). Orthographic projection, z-buffer, Lambert shading, light background.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

from print_check import load_stl

# (name, view direction pointing from the part towards the camera, up vector) - CAD frame, Z up
VIEWS = [
    ("isometric", np.array([1.0, -1.0, 0.8]), np.array([0.0, 0.0, 1.0])),
    ("front (X right, Z up)", np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])),
    ("top (X right, Y up)", np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0])),
]
BG = np.array([244, 242, 238], dtype=np.float32)       # warm light grey
INK = np.array([120, 130, 136], dtype=np.float32)      # slate


def _basis(view: np.ndarray, up: np.ndarray):
    f = view / np.linalg.norm(view)
    right = np.cross(up, f)
    if np.linalg.norm(right) < 1e-6:
        right = np.array([1.0, 0.0, 0.0])
    right /= np.linalg.norm(right)
    true_up = np.cross(f, right)
    return right, true_up, f


def _render_view(tris: np.ndarray, view, up, size: int) -> np.ndarray:
    right, true_up, f = _basis(view, up)
    pts = tris.reshape(-1, 3)
    u, v, d = pts @ right, pts @ true_up, pts @ f   # d: larger = closer to the camera
    pad = 0.08
    span = max(u.max() - u.min(), v.max() - v.min(), 1e-9)
    scale = size * (1 - 2 * pad) / span
    cu, cv = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
    px = ((u - cu) * scale + size / 2).reshape(-1, 3)
    py = (size / 2 - (v - cv) * scale).reshape(-1, 3)
    pz = d.reshape(-1, 3)

    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = _basis(view + np.array([0.3, 0.2, 0.6]), up)[2]
    shade = 0.35 + 0.65 * np.abs(n @ light)       # two-sided Lambert + ambient

    img = np.tile(BG, (size, size, 1))
    zbuf = np.full((size, size), -np.inf, dtype=np.float32)
    colors = INK[None, :] * shade[:, None] + 30

    # Most triangles of a finely tessellated part are smaller than a pixel: splat those in one vectorised pass
    # (after the big ones), the rest are rasterised individually below.
    w_px, h_px = px.max(1) - px.min(1), py.max(1) - py.min(1)
    tiny = (w_px < 1.2) & (h_px < 1.2)
    big_idx = np.nonzero(~tiny)[0]
    for i in big_idx:
        x0, x1 = int(max(np.floor(px[i].min()), 0)), int(min(np.ceil(px[i].max()), size - 1))
        y0, y1 = int(max(np.floor(py[i].min()), 0)), int(min(np.ceil(py[i].max()), size - 1))
        if x1 < x0 or y1 < y0:
            continue
        (ax, bx, cx), (ay, by, cy) = px[i], py[i]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        w1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not inside.any():
            continue
        z = w0 * pz[i, 0] + w1 * pz[i, 1] + w2 * pz[i, 2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        closer = inside & (z > sub)
        sub[closer] = z[closer]
        img[y0:y1 + 1, x0:x1 + 1][closer] = colors[i]

    t_idx = np.nonzero(tiny)[0]
    if len(t_idx):
        cx = np.clip(px[t_idx].mean(1).astype(int), 0, size - 1)
        cy = np.clip(py[t_idx].mean(1).astype(int), 0, size - 1)
        cz = pz[t_idx].mean(1)
        order = np.argsort(cz)                     # far -> near, so the nearest one is written last
        cx, cy, cz, t_idx = cx[order], cy[order], cz[order], t_idx[order]
        keep = cz > zbuf[cy, cx]                   # respect what the big triangles already drew
        cx, cy, cz, t_idx = cx[keep], cy[keep], cz[keep], t_idx[keep]
        zbuf[cy, cx] = cz
        img[cy, cx] = colors[t_idx]
    # thin outline where the part meets the background, for crisper silhouettes
    mask = np.isfinite(zbuf)
    edge = mask & ~(np.roll(mask, 1, 0) & np.roll(mask, -1, 0) & np.roll(mask, 1, 1) & np.roll(mask, -1, 1))
    img[edge] = (40, 40, 38)
    return np.clip(img, 0, 255).astype(np.uint8)


def _png(rgb: np.ndarray) -> bytes:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def render_views_png(stl_path: Path, size: int = 320) -> bytes:
    """Three views side by side (isometric | front | top), separated by thin gaps."""
    tris = load_stl(stl_path)
    panels = [_render_view(tris, v, u, size) for _, v, u in VIEWS]
    gap = np.tile(np.array([210, 206, 199], dtype=np.uint8), (size, 4, 1))
    row = np.concatenate([panels[0], gap, panels[1], gap, panels[2]], axis=1)
    return _png(row)
