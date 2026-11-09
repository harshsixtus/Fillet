"""Validation, metrics and STEP/STL export for a CadQuery result.

This module imports cadquery, so it is only imported inside the sandbox
subprocess (and by the eval/UI for pure helpers that do not need CAD).
"""
from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import cadquery as cq


class InvalidResult(Exception):
    """Raised when `result` is not a usable, valid solid."""


def to_shape(result: Any) -> cq.Shape:
    """Normalise a Workplane / Shape into a single cq.Shape and validate it."""
    if isinstance(result, cq.Workplane):
        objs = [o for o in result.vals() if isinstance(o, cq.Shape)]
    elif isinstance(result, cq.Shape):
        objs = [result]
    else:
        raise InvalidResult(
            f"`result` must be a cq.Workplane or cq.Shape, got {type(result).__name__}"
        )
    if not objs:
        raise InvalidResult("`result` contains no shapes (empty Workplane stack)")

    solids = [s for o in objs for s in o.Solids()]
    if not solids:
        raise InvalidResult("`result` contains no solids (only wires/faces/edges?)")
    if len(solids) > 1:
        # Pieces that touch or sit within a fraction of a millimetre of each other were meant to be one part
        # (e.g. bristle tufts on a head): fuse them with a small fuzzy tolerance.
        try:
            fused = solids[0].fuse(*solids[1:], tol=0.3).clean()
            if fused.isValid() and len(fused.Solids()) < len(solids):
                solids = fused.Solids()
        except Exception:  # noqa: BLE001 - keep the separate pieces; the pipeline asks the LLM to join them
            pass
    shape = solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids)

    if not shape.isValid():
        raise InvalidResult("The resulting solid is not valid (OCC isValid() is False)")
    if shape.Volume() <= 1e-6:
        raise InvalidResult("The resulting solid has zero or negative volume")
    return shape


def find_cylinders(shape: cq.Shape) -> list[dict]:
    """Full cylindrical features: holes/bores (concave) and round outer surfaces (convex).

    Faces that share one axis and radius are merged (OCC often splits a hole into two halves);
    partial cylinders such as edge fillets (< 300° in total) are ignored.
    """
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_REVERSED

    groups: dict[tuple, dict] = {}
    for f in shape.Faces():
        if f.geomType() != "CYLINDER":
            continue
        surf = BRepAdaptor_Surface(f.wrapped)
        cyl = surf.Cylinder()
        r = cyl.Radius()
        ax = cyl.Axis()
        d = ax.Direction()
        dv = [d.X(), d.Y(), d.Z()]
        k = max(range(3), key=lambda i: abs(dv[i]))
        if dv[k] < 0:
            dv = [-c for c in dv]                       # sign-agnostic axis direction
        loc = ax.Location()
        p = [loc.X(), loc.Y(), loc.Z()]
        t = sum(p[i] * dv[i] for i in range(3))
        foot = [p[i] - t * dv[i] for i in range(3)]     # axis line identified by its foot point
        # surface normal of a cylinder points away from the axis (if its frame is right-handed);
        # a reversed face means the material is outside -> it's a hole
        concave = (f.wrapped.Orientation() == TopAbs_REVERSED) == cyl.Position().Direct()
        key = (round(2 * r, 2), tuple(round(c, 3) for c in dv), tuple(round(c, 2) for c in foot), concave)
        g = groups.setdefault(key, {"d": round(2 * r, 2), "dir": dv, "center": foot, "hole": concave, "span": 0.0})
        g["span"] += abs(surf.LastUParameter() - surf.FirstUParameter())
    return [g for g in groups.values() if g["span"] >= 5.2]   # >= ~300 degrees


def summarize_cylinders(cyls: list[dict]) -> dict:
    holes: dict[float, int] = {}
    rounds: dict[float, int] = {}
    for c in cyls:
        bucket = holes if c["hole"] else rounds
        bucket[c["d"]] = bucket.get(c["d"], 0) + 1
    fmt = lambda b: [{"d": d, "n": n} for d, n in sorted(b.items())]   # noqa: E731
    return {"holes": fmt(holes), "rounds": fmt(rounds)}


def compute_metrics(shape: cq.Shape) -> dict:
    bb = shape.BoundingBox()
    try:
        feats = summarize_cylinders(find_cylinders(shape))
    except Exception:  # noqa: BLE001 - feature detection is best effort
        feats = {"holes": [], "rounds": []}
    return {
        "bbox_mm": [round(bb.xlen, 4), round(bb.ylen, 4), round(bb.zlen, 4)],
        "volume_mm3": round(shape.Volume(), 3),
        "surface_area_mm2": round(shape.Area(), 3),
        "num_solids": len(shape.Solids()),
        "is_valid": bool(shape.isValid()),
        **feats,
    }


def write_3mf(shape: cq.Shape, path: Path, tolerance: float = 0.05) -> None:
    """Minimal, slicer-friendly 3MF (millimetres) written from the tessellated shape."""
    verts, tris = shape.tessellate(tolerance, 0.1)
    v = "".join(f'<vertex x="{p.x:.5f}" y="{p.y:.5f}" z="{p.z:.5f}"/>' for p in verts)
    f = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    model = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Application">Fillet</metadata>'
             f'<resources><object id="1" type="model"><mesh><vertices>{v}</vertices><triangles>{f}</triangles></mesh></object></resources>'
             '<build><item objectid="1"/></build></model>')
    ctypes = ('<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
              '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
              '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("3D/3dmodel.model", model)


def export_preview(shape: cq.Shape, out_dir: Path, stem: str = "model",
                   print_mode: bool = False) -> tuple[cq.Shape, Path, Path]:
    """The fast part, needed right away: STEP (CAD) + STL (3D viewer). Returns the (bed-placed) shape."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if print_mode:  # drop the part onto the print bed (lowest point at Z=0)
        shape = shape.moved(cq.Location(cq.Vector(0, 0, -shape.BoundingBox().zmin)))
    step = out_dir / f"{stem}.step"
    stl = out_dir / f"{stem}.stl"
    cq.exporters.export(shape, str(step))
    cq.exporters.export(shape, str(stl), tolerance=0.05, angularTolerance=0.1)
    return shape, step, stl


def export_rest(shape: cq.Shape, out_dir: Path, stem: str = "model") -> None:
    """The slower extras (3MF, BREP, dimensioned drawings). Best effort: never fails the build."""
    try:
        write_3mf(shape, out_dir / f"{stem}.3mf")
    except Exception:  # noqa: BLE001
        pass
    _export_extras(shape, out_dir, stem)


def export_files(shape: cq.Shape, out_dir: Path, stem: str = "model",
                 print_mode: bool = False) -> tuple[Path, Path]:
    shape, step, stl = export_preview(shape, out_dir, stem, print_mode)
    export_rest(shape, out_dir, stem)
    return step, stl


VIEWS = {  # name -> (projection direction, screen-right direction); screen-up = direction × right = +Z
    "iso": ((1, -1, 0.8), (1, 1, 0)),
    "top": ((0, 0, 1), (1, 0, 0)),       # X right, Y up
    "front": ((0, -1, 0), (1, 0, 0)),    # X right, Z up
    "side": ((1, 0, 0), (0, 1, 0)),      # Y right, Z up
}


def _view_axes(direction, right):
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    return gp_Ax2(gp_Pnt(), gp_Dir(*direction), gp_Dir(*right))


def _export_svg_view(shape: cq.Shape, path: Path, direction, right, opt: dict) -> None:
    """CadQuery's SVG exporter only takes a view direction and lets OCC pick the in-plane axes,
    which turns front/side views sideways. Temporarily give it a fully specified frame (Z up)."""
    import cadquery.occ_impl.exporters.svg as svgmod

    original = svgmod.gp_Ax2
    svgmod.gp_Ax2 = lambda *_args: _view_axes(direction, right)
    try:
        cq.exporters.export(shape, str(path), opt={**opt, "projectionDir": direction})
    finally:
        svgmod.gp_Ax2 = original


SVG_W, SVG_H, SVG_MARGIN = 440, 360, 62
DIM_COLOR = "#6FA08E"   # sage


def _export_extras(shape: cq.Shape, out_dir: Path, stem: str) -> None:
    """BREP + dimensioned 2D drawing views (SVG). Failures are ignored."""
    try:
        shape.exportBrep(str(out_dir / f"{stem}.brep"))
    except Exception:  # noqa: BLE001
        pass
    try:
        cyls = find_cylinders(shape)
    except Exception:  # noqa: BLE001
        cyls = []
    for name, (direction, right) in VIEWS.items():
        path = out_dir / f"view_{name}.svg"
        try:
            _export_svg_view(
                shape, path, direction, right,
                {"width": SVG_W, "height": SVG_H, "marginLeft": SVG_MARGIN, "marginTop": SVG_MARGIN,
                 "showAxes": False, "strokeWidth": 0.7,
                 "strokeColor": (232, 229, 222), "hiddenColor": (100, 97, 92), "showHidden": True},
            )
        except Exception:  # noqa: BLE001
            continue
        try:
            path.write_text(annotate_view(path.read_text(encoding="utf-8"), shape, direction, cyls, right),
                            encoding="utf-8")
        except Exception:  # noqa: BLE001 - keep the plain view if annotation fails
            pass


def annotate_view(svg: str, shape: cq.Shape, direction: tuple, cyls: list[dict], right: tuple | None = None) -> str:
    """Add engineering-style dimensions (overall X/Y/Z extents and hole diameters) to a CadQuery SVG view.

    CadQuery projects a point p to (u, v) = (p·X, p·Y) where X/Y are the axes of gp_Ax2(origin, direction),
    then draws it at  x = s·(u + tx),  y = −s·(v + ty)  (from the <g transform="scale(s,-s) translate(tx,ty)">).
    """
    import math
    import re

    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    m = re.search(r'scale\(\s*([-\d.eE+]+)\s*,\s*-?[-\d.eE+]+\s*\)\s*translate\(\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\)', svg)
    if not m:
        return svg
    s, tx, ty = (float(g) for g in m.groups())
    ax = _view_axes(direction, right) if right else gp_Ax2(gp_Pnt(), gp_Dir(*direction))
    X = (ax.XDirection().X(), ax.XDirection().Y(), ax.XDirection().Z())
    Y = (ax.YDirection().X(), ax.YDirection().Y(), ax.YDirection().Z())
    nview = [c / math.sqrt(sum(d * d for d in direction)) for c in direction]

    def P(p):
        u = sum(p[i] * X[i] for i in range(3))
        v = sum(p[i] * Y[i] for i in range(3))
        return (s * (u + tx), -s * (v + ty))

    bb = shape.BoundingBox()
    lo, hi = (bb.xmin, bb.ymin, bb.zmin), (bb.xmax, bb.ymax, bb.zmax)
    lengths = (bb.xlen, bb.ylen, bb.zlen)
    center = P(tuple((lo[i] + hi[i]) / 2 for i in range(3)))
    out: list[str] = []

    def fmt(v: float) -> str:
        return f"{v:.1f}".rstrip("0").rstrip(".")

    def arrow(x, y, ux, uy):   # filled arrowhead at (x, y) pointing along (ux, uy)
        L, W = 7, 2.6
        bx, by = x - ux * L, y - uy * L
        return (f'<path d="M{x:.1f},{y:.1f} L{bx - uy * W:.1f},{by + ux * W:.1f} '
                f'L{bx + uy * W:.1f},{by - ux * W:.1f} Z" fill="{DIM_COLOR}" stroke="none"/>')

    def text(x, y, label, ang=0.0, anchor="middle"):
        return (f'<text x="{x:.1f}" y="{y:.1f}" transform="rotate({ang:.1f} {x:.1f} {y:.1f})" text-anchor="{anchor}" '
                f'dominant-baseline="middle" font-family="Inter Tight, Segoe UI, system-ui, sans-serif" font-size="12" '
                f'font-weight="600" fill="{DIM_COLOR}" paint-order="stroke" stroke="#171716" stroke-width="4">'
                f'{escape(label)}</text>')

    # ---- overall dimensions: for each axis, dimension the outermost bbox edge parallel to it
    used_sides: list[tuple[float, float]] = []
    for axis, axis_name in enumerate("XYZ"):
        if lengths[axis] < 1e-6:
            continue
        others = [i for i in range(3) if i != axis]
        best = None
        for a_lo in (lo, hi):
            for b_lo in (lo, hi):
                pa, pb = [0.0] * 3, [0.0] * 3
                pa[others[0]] = pb[others[0]] = a_lo[others[0]]
                pa[others[1]] = pb[others[1]] = b_lo[others[1]]
                pa[axis], pb[axis] = lo[axis], hi[axis]
                A, B = P(pa), P(pb)
                dx, dy = B[0] - A[0], B[1] - A[1]
                seg = math.hypot(dx, dy)
                if seg < 12:            # this axis points (almost) into the screen
                    continue
                ux, uy = dx / seg, dy / seg
                nx, ny = -uy, ux
                mx, my = (A[0] + B[0]) / 2, (A[1] + B[1]) / 2
                if (mx - center[0]) * nx + (my - center[1]) * ny < 0:
                    nx, ny = -nx, -ny
                # prefer the outermost edge; prefer bottom/left sides like a drawing, avoid a side already used
                out_score = (mx - center[0]) * nx + (my - center[1]) * ny
                pref = 0.6 * ny - 0.4 * nx
                clash = any(abs(nx - ux2) < .3 and abs(ny - uy2) < .3 for ux2, uy2 in used_sides)
                score = out_score + 25 * pref - (1000 if clash else 0)
                if best is None or score > best[0]:
                    best = (score, A, B, ux, uy, nx, ny)
        if not best:
            continue
        _, A, B, ux, uy, nx, ny = best
        used_sides.append((nx, ny))
        off = 26
        a2 = (A[0] + nx * off, A[1] + ny * off)
        b2 = (B[0] + nx * off, B[1] + ny * off)
        # extension lines (small gap from the part, slight overshoot past the dimension line)
        for p0, p1 in ((A, a2), (B, b2)):
            out.append(f'<line x1="{p0[0] + nx * 4:.1f}" y1="{p0[1] + ny * 4:.1f}" x2="{p1[0] + nx * 5:.1f}" '
                       f'y2="{p1[1] + ny * 5:.1f}" stroke="{DIM_COLOR}" stroke-width="0.8" opacity=".7"/>')
        out.append(f'<line x1="{a2[0]:.1f}" y1="{a2[1]:.1f}" x2="{b2[0]:.1f}" y2="{b2[1]:.1f}" '
                   f'stroke="{DIM_COLOR}" stroke-width="1.1"/>')
        out.append(arrow(a2[0], a2[1], -ux, -uy))
        out.append(arrow(b2[0], b2[1], ux, uy))
        ang = math.degrees(math.atan2(uy, ux))
        if ang > 90:
            ang -= 180
        elif ang < -90:
            ang += 180
        tx_, ty_ = (a2[0] + b2[0]) / 2 + nx * 11, (a2[1] + b2[1]) / 2 + ny * 11
        out.append(text(tx_, ty_, f"{fmt(lengths[axis])} mm  ({axis_name})", ang))

    # ---- hole / round diameters, on views that look straight down their axis
    seen: set = set()
    for c in cyls:
        dot = abs(sum(c["dir"][i] * nview[i] for i in range(3)))
        if dot < 0.999:
            continue
        cx, cy = P(c["center"])
        rpx = c["d"] / 2 * s
        key = (round(cx), round(cy), c["d"])
        if key in seen:
            continue
        seen.add(key)
        # leader from the circle edge (45° up-right) to a label
        ex, ey = cx + rpx * 0.707, cy - rpx * 0.707
        lx, ly = ex + 14, ey - 14
        label = f"⌀{fmt(c['d'])}" if c["hole"] else f"⌀{fmt(c['d'])} OD"
        out.append(f'<line x1="{ex:.1f}" y1="{ey:.1f}" x2="{lx:.1f}" y2="{ly:.1f}" stroke="#D27A52" stroke-width="0.9"/>')
        out.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="1.6" fill="#D27A52"/>')
        out.append(text(lx + 2, ly - 1, label, 0, "start").replace(DIM_COLOR, "#D27A52"))

    overlay = '<g class="dims">' + "".join(out) + "</g>"
    svg = re.sub(r"<svg\b", f'<svg viewBox="0 0 {SVG_W} {SVG_H}" preserveAspectRatio="xMidYMid meet"', svg, count=1)
    return svg.replace("</svg>", overlay + "</svg>")
