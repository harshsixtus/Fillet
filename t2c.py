"""t2c - small, robust CadQuery building blocks for generated code.

Generated scripts can `import t2c as h` (or use the pre-imported `h`). Every function returns a cq.Workplane
holding one solid, never raises for "cosmetic" steps (fillets), and keeps geometry simple enough for OCC.
All sizes are millimetres. Axes: X = length, Y = width/depth, Z = height (up).
"""
from __future__ import annotations

import math
from typing import Iterable, Sequence

import cadquery as cq

__all__ = ["box", "cylinder", "sphere", "loft_x", "loft_z", "revolve_z", "pins", "pin_grid", "union", "cut", "repair",
           "fillet", "chamfer", "shell", "holes_z", "bend_up"]


def _wp(shape) -> cq.Workplane:
    return shape if isinstance(shape, cq.Workplane) else cq.Workplane("XY").add(shape)


# ----------------------------------------------------------------------------- primitives
def box(length: float, width: float, height: float, at=(0, 0, 0), centered=(True, True, False)) -> cq.Workplane:
    """Box of size X*Y*Z. `at` is the centre of its footprint by default (base sits at at[2])."""
    return cq.Workplane("XY").box(length, width, height, centered=centered).translate(tuple(at))


def cylinder(d: float, h: float, at=(0, 0, 0), axis: str = "Z") -> cq.Workplane:
    """Cylinder of diameter d and length h starting at `at` and going +axis ('X', 'Y' or 'Z')."""
    plane = {"Z": "XY", "X": "YZ", "Y": "XZ"}[axis.upper()]
    wp = cq.Workplane(plane).circle(d / 2).extrude(h if axis.upper() != "Y" else -h)
    return wp.translate(tuple(at))


def sphere(d: float, at=(0, 0, 0)) -> cq.Workplane:
    return cq.Workplane("XY").sphere(d / 2).translate(tuple(at))


# ----------------------------------------------------------------------------- organic bodies
def _section(plane: str, origin, w: float, h: float, kind: str) -> cq.Wire:
    wp = cq.Workplane(plane, origin=tuple(origin))
    if kind == "ellipse" and abs(w - h) > 1e-6:
        wp = wp.ellipse(max(w, h) / 2, min(w, h) / 2, rotation_angle=0 if w >= h else 90)
    elif kind in ("ellipse", "circle"):
        wp = wp.circle(w / 2)
    elif kind == "rounded":   # rectangle with rounded corners
        wire = wp.rect(w, h).val()
        try:
            return wire.fillet2D(min(w, h) * 0.3, wire.Vertices())
        except Exception:  # noqa: BLE001
            return wire
    else:
        wp = wp.rect(w, h)
    return wp.val()


def loft_x(sections: Sequence[Sequence], kind: str = "ellipse", ruled: bool = False) -> cq.Workplane:
    """Smooth body along X through cross-sections. sections = [(x, width_y, height_z[, z_center]), ...]
    kind: 'ellipse' (default, organic), 'rect', 'rounded' or 'circle'. Great for handles, necks, blades, bottles
    lying down. Example (toothbrush handle): h.loft_x([(0, 14, 10), (90, 17, 12), (150, 9, 7)])."""
    wires = []
    for s in sections:
        x, w, hgt = s[0], s[1], s[2]
        zc = s[3] if len(s) > 3 else hgt / 2
        wires.append(_section("YZ", (x, 0, zc), w, hgt, kind))
    return _wp(cq.Solid.makeLoft(wires, ruled))


def loft_z(sections: Sequence[Sequence], kind: str = "ellipse", ruled: bool = False) -> cq.Workplane:
    """Smooth body going up Z through cross-sections. sections = [(z, width_x, depth_y), ...]
    Good for bottles, cups, knobs, feet, vases."""
    wires = [_section("XY", (0, 0, s[0]), s[1], s[2], kind) for s in sections]
    return _wp(cq.Solid.makeLoft(wires, ruled))


def revolve_z(profile: Sequence[Sequence[float]]) -> cq.Workplane:
    """Solid of revolution around the Z axis from a half-profile [(radius, z), ...] (radius >= 0).
    The profile is closed automatically along the axis. Good for knobs, bottles, cups, spools, wheels."""
    pts = [(max(r, 0.0), z) for r, z in profile]
    if pts[0][0] > 0:
        pts = [(0.0, pts[0][1])] + pts
    if pts[-1][0] > 0:
        pts = pts + [(0.0, pts[-1][1])]
    return cq.Workplane("XZ").polyline(pts).close().revolve(360, (0, 0, 0), (0, 1, 0))


# ----------------------------------------------------------------------------- repeated features
def _on_surface(body, pts, base_z: float, embed: float) -> list:
    """Keep only the (x, y) points whose pin foot actually sits inside `body` (so no pin floats in the air)."""
    solid = _wp(body).val()
    z = base_z - max(min(embed, 0.4), 0.05) / 2
    keep = []
    for x, y in pts:
        try:
            if solid.isInside(cq.Vector(x, y, z), 1e-3):
                keep.append((x, y))
        except Exception:  # noqa: BLE001
            keep.append((x, y))
    return keep


def pins(points: Iterable[Sequence[float]], d: float, h: float, base_z: float, embed: float = 0.4,
         kind: str = "circle", size2: float | None = None, on=None) -> cq.Workplane:
    """Many small pins/tufts/ribs standing up from z = base_z at (x, y) points. They are sunk `embed` mm into the
    surface below so they always fuse with it. kind 'circle' (d = diameter) or 'rect' (d x size2).
    on=<body>: keep only the pins whose foot really lands on that body (e.g. tufts that fall off a toothbrush
    head are dropped instead of floating)."""
    pts = [tuple(p[:2]) for p in points]
    if on is not None:
        pts = _on_surface(on, pts, base_z, embed) or pts
    wp = cq.Workplane("XY", origin=(0, 0, base_z - embed)).pushPoints(pts)
    wp = wp.circle(d / 2) if kind == "circle" else wp.rect(d, size2 or d)
    return wp.extrude(h + embed)


def pin_grid(center, nx: int, ny: int, pitch_x: float, pitch_y: float, d: float, h: float, base_z: float,
             **kw) -> cq.Workplane:
    """Rectangular grid of pins/tufts (e.g. toothbrush bristles, studs) centred on center=(x, y).
    Pass on=<body> to keep only the pins that land on that body."""
    cx, cy = center[0], center[1]
    pts = [(cx + (i - (nx - 1) / 2) * pitch_x, cy + (j - (ny - 1) / 2) * pitch_y) for i in range(nx) for j in range(ny)]
    return pins(pts, d, h, base_z, **kw)


def holes_z(body: cq.Workplane, points: Iterable[Sequence[float]], d: float) -> cq.Workplane:
    """Vertical through-holes of diameter d at (x, y) points, all the way through the body."""
    bb = _wp(body).val().BoundingBox()
    tool = cq.Workplane("XY", origin=(0, 0, bb.zmin - 1)).pushPoints([tuple(p[:2]) for p in points]) \
        .circle(d / 2).extrude(bb.zlen + 2)
    return cut(body, tool)


# ----------------------------------------------------------------------------- booleans (robust)
def repair(shape):
    """OpenCascade's shape healing: makes most 'not valid' boolean results valid again."""
    try:
        if not shape.isValid():
            fixed = shape.fix()
            if fixed.isValid():
                return fixed
    except Exception:  # noqa: BLE001
        pass
    return shape


def _drop_floaters(shape, min_fraction: float):
    """Remove tiny loose fragments (< min_fraction of the biggest piece's volume): stray pins, slivers."""
    solids = shape.Solids()
    if len(solids) <= 1:
        return shape
    vols = [s.Volume() for s in solids]
    big = max(vols)
    keep = [s for s, v in zip(solids, vols) if v >= min_fraction * big]
    return keep[0] if len(keep) == 1 else cq.Compound.makeCompound(keep)


def union(*parts, tol: float = 0.05, drop_floaters: float = 0.05) -> cq.Workplane:
    """Fuse everything into one solid. Uses a small fuzzy tolerance so parts that just touch still join, heals
    invalid results, and drops tiny loose fragments (< drop_floaters x the main body's volume; 0 keeps them)."""
    shapes = [_wp(p).val() for p in parts if p is not None]
    if not shapes:
        raise ValueError("union() needs at least one part")
    out = shapes[0]
    if len(shapes) > 1:
        try:
            out = out.fuse(*shapes[1:], tol=tol).clean()
        except Exception:  # noqa: BLE001 - fall back to plain sequential unions
            wp = _wp(shapes[0])
            for s in shapes[1:]:
                wp = wp.union(_wp(s))
            out = wp.clean().val()
    out = repair(out)
    if drop_floaters:
        out = repair(_drop_floaters(out, drop_floaters))
    return _wp(out)


def cut(body, *tools) -> cq.Workplane:
    wp = _wp(body)
    for t in tools:
        wp = wp.cut(_wp(t))
    return wp.clean()


# ----------------------------------------------------------------------------- finishing (never crash)
SAFE_EDGE_TYPES = ("LINE", "CIRCLE")   # filleting free-form (BSPLINE) edges can hang OpenCascade
MAX_FILLET_EDGES = 32


def _safe_edges(wp: cq.Workplane, selector: str | None) -> list:
    try:
        edges = (wp.edges(selector) if selector else wp.edges()).vals()
    except Exception:  # noqa: BLE001
        return []
    edges = [e for e in edges if e.geomType() in SAFE_EDGE_TYPES]
    return edges if len(edges) <= MAX_FILLET_EDGES else []


def fillet(body, r: float, selector: str | None = None) -> cq.Workplane:
    """Round edges (all edges, or those matching a CadQuery selector like '|Z' or '>Z'). Only straight/circular
    edges are rounded (curved free-form edges are skipped), and if the fillet is not possible it tries a smaller
    radius and finally returns the body unchanged instead of failing or hanging."""
    wp = _wp(body)
    edges = _safe_edges(wp, selector)
    if not edges:
        return wp
    shape = wp.val()
    for rr in (r, r * 0.6, r * 0.35):
        try:
            res = shape.fillet(rr, edges)
            if res.isValid():
                return _wp(res)
        except Exception:  # noqa: BLE001
            continue
    return wp


def chamfer(body, d: float, selector: str | None = None) -> cq.Workplane:
    wp = _wp(body)
    edges = _safe_edges(wp, selector)
    if not edges:
        return wp
    shape = wp.val()
    for dd in (d, d * 0.5):
        try:
            res = shape.chamfer(dd, None, edges)
            if res.isValid():
                return _wp(res)
        except Exception:  # noqa: BLE001
            continue
    return wp


def shell(body, thickness: float, open_face: str | None = ">Z") -> cq.Workplane:
    """Hollow the body with the given wall thickness, removing `open_face` (None = closed hollow)."""
    wp = _wp(body)
    try:
        res = (wp.faces(open_face).shell(-thickness) if open_face else wp.shell(-thickness))
        if res.val().isValid():
            return res
    except Exception:  # noqa: BLE001
        pass
    return wp


def bend_up(body, angle_deg: float, pivot_x: float) -> cq.Workplane:
    """Tilt a body upward around the Y axis at x = pivot_x (e.g. angle a toothbrush head slightly)."""
    return _wp(body).rotate((pivot_x, 0, 0), (pivot_x, 1, 0), -angle_deg)
