"""FDM 3D-printing report from an STL + sandbox metrics (pure numpy, no CAD needed)."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

PRINTERS = {
    "Creality Ender-3 (220 × 220 × 250)": (220, 220, 250),
    "Prusa MK4 (250 × 210 × 220)": (250, 210, 220),
    "Bambu Lab P1S / X1C (256 × 256 × 256)": (256, 256, 256),
    "Prusa Mini (180 × 180 × 180)": (180, 180, 180),
    "Small printer (150 × 150 × 150)": (150, 150, 150),
}
MATERIALS = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "TPU": 1.21}  # g/cm3
FILAMENT_AREA_MM2 = np.pi * (1.75 / 2) ** 2


def load_stl(path: Path) -> np.ndarray:
    """Return triangles as an (n, 3, 3) array (binary or ASCII STL)."""
    data = Path(path).read_bytes()
    if len(data) >= 84 and len(data) == 84 + 50 * struct.unpack("<I", data[80:84])[0]:
        n = struct.unpack("<I", data[80:84])[0]
        rec = np.frombuffer(data[84:], dtype=np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")]), count=n)
        return rec["v"].astype(np.float64)
    pts = [list(map(float, ln.split()[1:4])) for ln in data.decode("ascii", "ignore").splitlines()
           if ln.strip().startswith("vertex")]
    return np.array(pts, dtype=np.float64).reshape(-1, 3, 3)


def analyze(stl_path: Path, metrics: dict, build_volume: tuple[float, float, float],
            material: str = "PLA", infill: float = 0.2, overhang_deg: float = 45.0) -> dict:
    tris = load_stl(stl_path)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    cross = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cross, axis=1)
    nz = np.divide(cross[:, 2], 2 * area, out=np.zeros_like(area), where=area > 1e-12)
    zmin = tris[:, :, 2].min()
    zc = tris[:, :, 2].mean(axis=1) - zmin
    total = float(area.sum())

    bed_contact = float(area[(nz < -0.99) & (zc < 0.05)].sum())
    over_mask = (nz < -np.cos(np.radians(overhang_deg))) & (zc > 0.2)
    overhang = float(area[over_mask].sum())
    overhang_pct = 100 * overhang / total if total else 0.0

    x, y, z = metrics["bbox_mm"]
    bx, by, bz = build_volume
    fits = z <= bz and ((x <= bx and y <= by) or (x <= by and y <= bx))

    vol = metrics["volume_mm3"]
    shell = min(vol, metrics["surface_area_mm2"] * 1.2)       # ~3 perimeters + top/bottom
    used = shell + (vol - shell) * infill                      # mm3 of plastic
    grams = used / 1000 * MATERIALS[material]
    length_m = used / FILAMENT_AREA_MM2 / 1000
    hours = used / 8.0 * 1.4 / 3600                            # ~8 mm3/s effective + travel/overhead

    warnings = []
    if not fits:
        warnings.append(f"Does not fit the build volume {bx:g} × {by:g} × {bz:g} mm; scale it or split into parts.")
    if bed_contact < 0.02 * total or bed_contact < 25:
        warnings.append("Small contact area with the bed: use a brim or reorient the part.")
    if overhang_pct > 2:
        warnings.append(f"{overhang_pct:.0f}% of the surface overhangs more than {overhang_deg:g}°: expect supports.")
    if min(x, y, z) < 1.2:
        warnings.append("A dimension is below 1.2 mm; thin features may not print.")
    if metrics["num_solids"] > 1:
        warnings.append(f"{metrics['num_solids']} separate solids: they will be printed as separate pieces.")

    return {
        "fits": bool(fits), "overhang_pct": round(overhang_pct, 1), "bed_contact_mm2": round(bed_contact, 1),
        "supports": overhang_pct > 2, "weight_g": round(grams, 1), "filament_m": round(length_m, 2),
        "hours": round(hours, 1), "material": material, "infill": infill, "warnings": warnings,
    }
