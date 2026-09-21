"""Content-first parser for legacy/headerless NC drill (.tap) output.

Supports files such as:
    %
    T1C0.027F200S100
    X015125Y021687
    ...
    M30

This family uses metric fixed 3-decimal coordinates while the C tool
size is commonly expressed in inches. The distinction is detected from
content rather than trusting the filename extension.
"""
from pathlib import Path
import re

_TOOL_RE = re.compile(
    r"^\s*T(?P<num>\d+)"
    r"(?:F[+-]?\d+(?:\.\d+)?|S[+-]?\d+(?:\.\d+)?|C[+-]?\d+(?:\.\d+)?)+\s*$",
    re.I,
)
_C_RE = re.compile(r"C\s*(?P<dia>[+-]?\d+(?:\.\d+)?)", re.I)
_COORD_RE = re.compile(
    r"^\s*X(?P<x>[+-]?\d+)Y(?P<y>[+-]?\d+)\s*$",
    re.I,
)


def _tool_id(n):
    return f"T{int(n):02d}"


def looks_like_headerless_nc_drill(text: str) -> bool:
    lines = [ln.strip().upper() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return False
    if any(ln == "M48" for ln in lines):
        return False
    tool_defs = [ln for ln in lines if _TOOL_RE.match(ln)]
    coords = [ln for ln in lines if _COORD_RE.match(ln)]
    # Strong content signature for this legacy CAM family.
    if len(tool_defs) < 1 or len(coords) < 2:
        return False
    if not any(ln == "%" for ln in lines[:3]):
        return False
    return True


def _infer_coordinate_decimals(coords):
    # This legacy format writes six integer coordinate digits as thousandths.
    # Prefer the explicit six-digit convention when present.
    lengths = []
    for x, y in coords:
        if x.lstrip("+-").isdigit():
            lengths.append(len(x.lstrip("+-")))
        if y.lstrip("+-").isdigit():
            lengths.append(len(y.lstrip("+-")))
    if lengths and all(n == 6 for n in lengths):
        return 3, "fixed_6_digits_as_3_decimal_mm"
    # Conservative fallback for shorter legacy coordinates: infer three
    # decimal places from the fixed-width integer coordinate convention.
    return 3, "legacy_fixed_integer_3_decimal_mm"


def parse_headerless_nc_drill(file_path):
    file_path = Path(file_path)
    text = file_path.read_text(encoding="utf-8", errors="ignore")
    if not looks_like_headerless_nc_drill(text):
        return None

    tools = {}
    current_tool = None
    raw_coords = []

    for raw in text.splitlines():
        line = raw.strip().upper()
        if not line or line.startswith(";"):
            continue
        m = _TOOL_RE.match(line)
        if m:
            cm = _C_RE.search(line)
            if not cm:
                continue
            tool = _tool_id(m.group("num"))
            dia_in = float(cm.group("dia"))
            tools[tool] = {
                "tool": tool,
                "diameter_in": dia_in,
                "diameter_mm": dia_in * 25.4,
                "hits": 0,
                "slots": 0,
            }
            current_tool = tool
            continue
        m = re.match(r"^T(\d+)\s*$", line, re.I)
        if m:
            current_tool = _tool_id(m.group(1))
            continue
        m = _COORD_RE.match(line)
        if m and current_tool in tools:
            raw_coords.append((m.group("x"), m.group("y"), current_tool))

    decimals, coord_mode = _infer_coordinate_decimals(
        [(x, y) for x, y, _ in raw_coords]
    )
    primitives = []
    for x_raw, y_raw, tool in raw_coords:
        x = int(x_raw) / (10 ** decimals)
        y = int(y_raw) / (10 ** decimals)
        dia = tools[tool]["diameter_mm"]
        primitives.append({
            "type": "drill",
            "center": [x, y],
            "diameter": dia,
            "tool": tool,
            "polarity": "dark",
        })
        tools[tool]["hits"] += 1

    tool_list = []
    for tool in sorted(tools, key=lambda s: int(s[1:])):
        t = tools[tool]
        tool_list.append({
            "tool": tool,
            "diameter": round(t["diameter_mm"], 4),
            "diameter_in": round(t["diameter_in"], 6),
            "hits": t["hits"],
            "slots": 0,
        })

    if primitives:
        xs, ys = [], []
        for p in primitives:
            x, y = p["center"]
            r = p["diameter"] / 2.0
            xs.extend((x-r, x+r))
            ys.extend((y-r, y+r))
        bounds = {
            "x_min": min(xs), "x_max": max(xs),
            "y_min": min(ys), "y_max": max(ys),
            "width_mm": max(xs)-min(xs),
            "height_mm": max(ys)-min(ys),
            "area_mm2": (max(xs)-min(xs))*(max(ys)-min(ys)),
        }
    else:
        bounds = None

    return {
        "filename": file_path.name,
        "primitives": primitives,
        "bounds": bounds,
        "primitive_errors": 0,
        "tools": tool_list,
        "drill_count": len(primitives),
        "source_info": {
            "file_type": "Excellon / legacy NC drill",
            "format": "headerless legacy TAP",
            "source_units": "metric coordinates + inch tool diameters",
            "coordinate_format": "3 decimal places",
            "coordinate_mode": coord_mode,
            "tool_diameter_units": "inch",
            "normalized_units": "mm",
        },
        "method": "legacy_headerless_tap",
    }
