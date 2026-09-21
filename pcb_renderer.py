"""
PCB Preview Renderer
--------------------
Generates clean, separate PCB previews from Gerber + Excellon files.

Outputs:
    renders/pcb_top_2d.png
    renders/pcb_bottom_2d.png
    renders/pcb_top_3d.png
    renders/pcb_bottom_3d.png

Compatibility:
    - Keeps pcb_2d_preview.png as the TOP 2D preview.
    - Keeps pcb_3d_preview.png as the TOP 3D preview.
    - Uses gerber.read() for Gerber files.
    - Uses a built-in Excellon parser; it does NOT depend on
      gerber.read_excellon(), which is missing in some gerber versions.
"""

from pathlib import Path
import re
import math

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import gerber
import gerber_patch



# ============================================================
# FILE / TEXT HELPERS
# ============================================================

def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _safe_read(path):
    """Read Gerber without allowing one bad layer to stop all previews."""
    try:
        return gerber.read(str(path))
    except Exception as e:
        print(f"Gerber read error: {path}: {e}")
        return None


# ============================================================
# GERBER COORDINATE PARSING
# ============================================================

def _gerber_format(text):
    """
    Return coordinate decimals and units.

    Typical:
        %FSLAX24Y24*%
        %MOMM*%
        %MOIN*%
    """
    xd = yd = 4
    units = "mm"

    m = re.search(r"%FSL[AI]X(\d)(\d)Y(\d)(\d)\*%", text, re.I)
    if m:
        xd = int(m.group(2))
        yd = int(m.group(4))

    if re.search(r"%MOIN\*%", text, re.I):
        units = "inch"
    elif re.search(r"%MOMM\*%", text, re.I):
        units = "mm"

    return xd, yd, units


def _coord(raw, decimals):
    if raw is None:
        return None

    raw = str(raw).strip()
    if not raw:
        return None

    sign = -1 if raw.startswith("-") else 1
    raw = raw.lstrip("+-")

    try:
        if "." in raw:
            value = float(raw)
        else:
            value = int(raw) / (10 ** decimals)
        return sign * value
    except Exception:
        return None


def _gerber_points(path):
    """
    Extract coordinate points from a Gerber file.

    This is intentionally independent of the gerber library's geometry
    validation, because some malformed-but-readable mask files can make
    gerber.read() fail.
    """
    text = _read_text(path)
    if not text:
        return []

    xd, yd, units = _gerber_format(text)

    x = None
    y = None
    out = []

    for raw in text.splitlines():
        line = raw.strip()

        if not line:
            continue
        if line.startswith("%"):
            continue
        if line.startswith("G04"):
            continue
        if line.startswith(";"):
            continue

        xm = re.search(r"X([+-]?\d+(?:\.\d+)?)", line, re.I)
        ym = re.search(r"Y([+-]?\d+(?:\.\d+)?)", line, re.I)
        dm = re.search(r"D0?([123])", line, re.I)

        if xm:
            x = _coord(xm.group(1), xd)
        if ym:
            y = _coord(ym.group(1), yd)

        if x is None or y is None:
            continue

        d = dm.group(1) if dm else None
        out.append((x, y, d))

    if units == "inch":
        out = [(x * 25.4, y * 25.4, d) for x, y, d in out]

    return out


# ============================================================
# BOARD OUTLINE / BOUNDS
# ============================================================

def _find_outline(extracted_path, project_files):
    root = Path(extracted_path)

    # First trust main.py's layer classification.
    for item in project_files:
        if item.get("layer") == "Board Outline":
            filename = item.get("filename", "")
            p = root / filename
            if p.exists():
                return p

    # Fallbacks for common Gerber naming.
    patterns = (
        "*.GKO",
        "*.gko",
        "*.GM1",
        "*.gm1",
        "*.GML",
        "*.gml",
        "*outline*",
        "*Outline*",
        "*OUTLINE*",
        "*profile*",
        "*Profile*",
        "*PROFILE*",
        "*.edge*",
        "*.EDGE*",
        "*cut*",
        "*CUT*",
    )

    for pattern in patterns:
        matches = list(root.glob(pattern))
        if matches:
            return matches[0]

    return None


def _bounds_from_points(points):
    if not points:
        return None

    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]

    if not xs or not ys:
        return None

    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)

    if max_x <= min_x or max_y <= min_y:
        return None

    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
    }


def get_board_bounds(extracted_path, project_files):
    """
    Prefer raw outline coordinates so an aperture width does not
    accidentally enlarge the board dimensions.
    """
    outline = _find_outline(extracted_path, project_files)

    if outline is not None:
        points = _gerber_points(outline)
        bounds = _bounds_from_points(points)
        if bounds:
            return bounds

        g = _safe_read(outline)
        if g is not None:
            raw_points = []
            for primitive in getattr(g, "primitives", []):
                try:
                    if hasattr(primitive, "start"):
                        raw_points.append(primitive.start)
                    if hasattr(primitive, "end"):
                        raw_points.append(primitive.end)
                    vertices = getattr(primitive, "vertices", None)
                    if vertices:
                        raw_points.extend(list(vertices))
                    if hasattr(primitive, "position"):
                        raw_points.append(primitive.position)
                except Exception:
                    continue
            bounds = _bounds_from_points(raw_points)
            if bounds:
                return bounds

    # Fallback to computing bounds from all Gerber layer primitives if outline file yields no bounds
    all_points = []
    root = Path(extracted_path)
    for gfile in root.glob("*"):
        if gfile.is_file() and gfile.suffix.lower() in {".gbr", ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".ger", ".pho"}:
            g = _safe_read(gfile)
            if g is not None:
                for primitive in getattr(g, "primitives", []):
                    try:
                        if hasattr(primitive, "start"):
                            all_points.append(primitive.start)
                        if hasattr(primitive, "end"):
                            all_points.append(primitive.end)
                        if hasattr(primitive, "position"):
                            all_points.append(primitive.position)
                        vertices = getattr(primitive, "vertices", None)
                        if vertices:
                            all_points.extend(list(vertices))
                    except Exception:
                        pass
    return _bounds_from_points(all_points)


def mm_to_pixel(x, y, bounds, scale, padding):
    px = int(round(
        (float(x) - bounds["min_x"]) * scale + padding
    ))

    py = int(round(
        (bounds["max_y"] - float(y)) * scale + padding
    ))

    return px, py


# ============================================================
# EXCELLON DRILL PARSER
# ============================================================

def _parse_excellon_drill(path):
    """
    Built-in parser for common Excellon drill files using gerber_viewer geometry engine.
    """
    try:
        from gerber_viewer import read_excellon_geometry
        res = read_excellon_geometry(path)
        prims = res.get("primitives", [])
        if prims:
            hits = []
            for p in prims:
                c = p.get("center")
                d = p.get("diameter", 0.0)
                if c and len(c) >= 2:
                    hits.append((c[0], c[1], d))
            if hits:
                return hits
    except Exception:
        pass

    # Try reading as Gerber format drill file (RS-274X / Gerber X2 drill files)
    try:
        g = gerber.read(str(path))
        if g is not None:
            if str(getattr(g, "units", "metric")).lower() == "inch":
                g.to_metric()
            hits = []
            for prim in getattr(g, "primitives", []) or []:
                pos = getattr(prim, "position", getattr(prim, "center", None))
                dia = getattr(prim, "diameter", getattr(getattr(prim, "aperture", None), "diameter", None))
                if pos and dia is not None and float(dia) > 0:
                    hits.append((pos[0], pos[1], float(dia)))
            if hits:
                return hits
    except Exception:
        pass

    text = _read_text(path)
    if not text:
        return []

    # Units.
    if re.search(r"\bMETRIC\b", text, re.I):
        units = "mm"
    elif re.search(r"\bINCH\b", text, re.I):
        units = "inch"
    else:
        units = "mm"

    # Common format statement.
    decimals = 4
    suppression = "L"

    fmt = re.search(
        r"(?:INCH|METRIC)\s*,?\s*([LT])?\s*"
        r"(\d+)\.(\d+)",
        text,
        re.I,
    )

    if fmt:
        suppression = (fmt.group(1) or "L").upper()
        decimals = int(fmt.group(3))

    # Tool table.
    tools = {}

    for match in re.finditer(
        r"^\s*T(\d+)\s*C\s*([0-9]+(?:\.[0-9]+)?)",
        text,
        re.I | re.M,
    ):
        tools[match.group(1)] = float(match.group(2))

    current_tool = None
    hits = []

    def parse_axis(raw):
        raw = str(raw).strip()

        if not raw:
            return None

        sign = -1 if raw.startswith("-") else 1
        raw = raw.lstrip("+-")

        try:
            # Explicit decimal.
            if "." in raw:
                value = float(raw)
            else:
                # Fixed decimal format.
                value = int(raw) / (10 ** decimals)

            if units == "inch":
                value *= 25.4

            return sign * value

        except Exception:
            return None

    for raw in text.splitlines():
        line = raw.strip().upper()

        if not line:
            continue

        if line.startswith(";"):
            continue

        if line in {"%", "M48", "M95", "M30", "M00"}:
            continue

        # Tool selection / definition.
        tool_match = re.match(
            r"^T(\d+)(?:C([0-9]+(?:\.[0-9]+)?))?",
            line,
        )

        if tool_match:
            current_tool = tool_match.group(1)

            if tool_match.group(2):
                tools[current_tool] = float(tool_match.group(2))

            continue

        if current_tool not in tools:
            continue

        xm = re.search(r"X([+-]?[0-9]+(?:\.[0-9]+)?)", line)
        ym = re.search(r"Y([+-]?[0-9]+(?:\.[0-9]+)?)", line)

        if not xm or not ym:
            continue

        x = parse_axis(xm.group(1))
        y = parse_axis(ym.group(1))

        if x is None or y is None:
            continue

        diameter = tools[current_tool]

        if units == "inch":
            diameter *= 25.4

        hits.append((x, y, diameter))

    return hits


def draw_drill_layer(
    draw,
    file_path,
    bounds,
    scale,
    padding,
    hole_fill=(18, 18, 18),
    ring_fill=None,
):
    hits = _parse_excellon_drill(file_path)

    count = 0

    for x_mm, y_mm, diameter_mm in hits:
        try:
            x, y = mm_to_pixel(
                x_mm,
                y_mm,
                bounds,
                scale,
                padding,
            )

            radius = max(
                2.0,
                float(diameter_mm) * scale / 2.0,
            )

            if ring_fill is not None:
                outer = radius + max(1.0, scale * 0.10)

                draw.ellipse(
                    [
                        (int(x - outer), int(y - outer)),
                        (int(x + outer), int(y + outer)),
                    ],
                    fill=ring_fill,
                )

            draw.ellipse(
                [
                    (int(x - radius), int(y - radius)),
                    (int(x + radius), int(y + radius)),
                ],
                fill=hole_fill,
            )

            count += 1

        except Exception as e:
            print(
                f"Drill render error in "
                f"{Path(file_path).name}: {e}"
            )

    if count:
        print(
            f"Rendered {count} drill hits from "
            f"{Path(file_path).name}"
        )

    return count


# ============================================================
# GERBER PRIMITIVE HELPERS
# ============================================================

def _primitive_aperture_diameter(primitive):
    try:
        aperture = getattr(primitive, "aperture", None)

        diameter = getattr(
            aperture,
            "diameter",
            None,
        )

        if diameter:
            return float(diameter)

    except Exception:
        pass

    return 0.0


def _safe_rectangle(draw, p1, p2, fill):
    left = min(int(p1[0]), int(p2[0]))
    right = max(int(p1[0]), int(p2[0]))
    top = min(int(p1[1]), int(p2[1]))
    bottom = max(int(p1[1]), int(p2[1]))

    draw.rectangle(
        [(left, top), (right, bottom)],
        fill=fill,
    )


def _safe_line(draw, p1, p2, fill, width=1):
    draw.line(
        [
            (int(p1[0]), int(p1[1])),
            (int(p2[0]), int(p2[1])),
        ],
        fill=fill,
        width=max(1, int(width)),
    )


def _copper_colors(fill):
    """
    Return a dark edge and a copper highlight derived from the
    requested copper base.
    """
    r, g, b = fill

    edge = (
        max(0, int(r * 0.62)),
        max(0, int(g * 0.62)),
        max(0, int(b * 0.62)),
    )

    highlight = (
        min(255, int(r * 1.10)),
        min(255, int(g * 1.10)),
        min(255, int(b * 1.10)),
    )

    return edge, highlight


# ============================================================
# GERBER LAYER RENDERING
# ============================================================

def _draw_single_primitive(draw, primitive, bounds, scale, padding, fill, copper, edge_fill, highlight_fill):
    if primitive is None:
        return 0

    primitive_type = type(primitive).__name__.lower()

    # 1) Aperture Macro Group / Outline / Region via gerber_viewer conversion
    if "macro" in primitive_type or "amgroup" in primitive_type or "outline" in primitive_type or "region" in primitive_type or (hasattr(primitive, "primitives") and not hasattr(primitive, "vertices")):
        try:
            from gerber_viewer import _convert_primitive
            converted = _convert_primitive(primitive)
            if converted:
                items = converted if isinstance(converted, list) else [converted]
                count = 0
                for item in items:
                    if not item or not isinstance(item, dict):
                        continue
                    itype = item.get("type")
                    if itype == "region":
                        for path in item.get("paths", []):
                            if len(path) >= 3:
                                pts = [mm_to_pixel(p[0], p[1], bounds, scale, padding) for p in path]
                                draw.polygon(pts, fill=fill)
                                if copper:
                                    draw.line(pts + [pts[0]], fill=edge_fill, width=max(1, int(scale * 0.10)))
                                count += 1
                    elif itype == "circle":
                        c = item.get("center")
                        d = item.get("diameter", 0.0)
                        if c and d > 0:
                            px, py = mm_to_pixel(c[0], c[1], bounds, scale, padding)
                            radius = max(1, int(round(float(d) * scale / 2.0)))
                            draw.ellipse([(px - radius, py - radius), (px + radius, py + radius)], fill=fill)
                            if copper:
                                draw.ellipse([(px - radius - 1, py - radius - 1), (px + radius + 1, py + radius + 1)], outline=edge_fill, width=max(1, int(scale * 0.10)))
                            count += 1
                    elif itype == "rectangle":
                        pos = item.get("position")
                        w, h = item.get("width", 0.0), item.get("height", 0.0)
                        if pos and w > 0 and h > 0:
                            cx, cy = pos[0], pos[1]
                            p1 = mm_to_pixel(cx - w / 2.0, cy - h / 2.0, bounds, scale, padding)
                            p2 = mm_to_pixel(cx + w / 2.0, cy + h / 2.0, bounds, scale, padding)
                            _safe_rectangle(draw, p1, p2, fill)
                            if copper:
                                left, right = min(p1[0], p2[0]), max(p1[0], p2[0])
                                top, bottom = min(p1[1], p2[1]), max(p1[1], p2[1])
                                draw.rectangle([(left, top), (right, bottom)], outline=edge_fill, width=max(1, int(scale * 0.10)))
                            count += 1
                if count > 0:
                    return count
        except Exception:
            pass

    # 2) Line
    if "line" in primitive_type:
        start = getattr(primitive, "start", None)
        end = getattr(primitive, "end", None)
        if start is not None and end is not None:
            p1 = mm_to_pixel(start[0], start[1], bounds, scale, padding)
            p2 = mm_to_pixel(end[0], end[1], bounds, scale, padding)
            diameter = _primitive_aperture_diameter(primitive)
            width = max(1, int(round(diameter * scale))) if diameter > 0 else 1
            if copper:
                _safe_line(draw, p1, p2, edge_fill, width + max(1, int(scale * 0.10)))
                _safe_line(draw, p1, p2, fill, width)
                if width >= 4:
                    _safe_line(draw, (p1[0], p1[1] - 1), (p2[0], p2[1] - 1), highlight_fill, max(1, width // 5))
            else:
                _safe_line(draw, p1, p2, fill, width)
            return 1

    # Extract position/center
    position = getattr(primitive, "position", getattr(primitive, "center", None))
    aperture = getattr(primitive, "aperture", None)

    # 3) Circle
    diameter = getattr(primitive, "diameter", getattr(aperture, "diameter", None))
    if ("circle" in primitive_type or (position is not None and diameter is not None and "rect" not in primitive_type and "obround" not in primitive_type)) and "macro" not in primitive_type:
        if position is not None and diameter is not None:
            px, py = mm_to_pixel(position[0], position[1], bounds, scale, padding)
            radius = max(1, int(round(float(diameter) * scale / 2.0)))
            if copper:
                draw.ellipse([(px - radius - 1, py - radius - 1), (px + radius + 1, py + radius + 1)], fill=edge_fill)
                draw.ellipse([(px - radius, py - radius), (px + radius, py + radius)], fill=fill)
                if radius >= 4:
                    hr = max(1, radius // 5)
                    draw.ellipse([(px - radius + hr, py - radius + hr), (px + radius - hr, py + radius - hr)], outline=highlight_fill, width=max(1, radius // 8))
            else:
                draw.ellipse([(px - radius, py - radius), (px + radius, py + radius)], fill=fill)
            return 1

    # 4) Rectangle
    if "rectangle" in primitive_type or "rect" in primitive_type:
        bbox = getattr(primitive, "bounding_box", None)
        if bbox:
            x1, x2 = bbox[0]
            y1, y2 = bbox[1]
        elif position is not None:
            w = float(getattr(primitive, "width", getattr(aperture, "width", 0.0)) or 0.0)
            h = float(getattr(primitive, "height", getattr(aperture, "height", 0.0)) or 0.0)
            if w > 0 and h > 0:
                cx, cy = position[0], position[1]
                x1, x2 = cx - w / 2.0, cx + w / 2.0
                y1, y2 = cy - h / 2.0, cy + h / 2.0
            else:
                x1 = x2 = y1 = y2 = None
        else:
            x1 = x2 = y1 = y2 = None

        if x1 is not None and x2 is not None and y1 is not None and y2 is not None:
            p1 = mm_to_pixel(x1, y1, bounds, scale, padding)
            p2 = mm_to_pixel(x2, y2, bounds, scale, padding)
            _safe_rectangle(draw, p1, p2, fill)
            if copper:
                left, right = min(p1[0], p2[0]), max(p1[0], p2[0])
                top, bottom = min(p1[1], p2[1]), max(p1[1], p2[1])
                draw.rectangle([(left, top), (right, bottom)], outline=edge_fill, width=max(1, int(scale * 0.10)))
            return 1

    # 5) Obround / Oval / Oblong
    if "obround" in primitive_type or "oval" in primitive_type or "oblong" in primitive_type:
        if position is not None:
            w = float(getattr(primitive, "width", getattr(aperture, "width", 0.0)) or 0.0)
            h = float(getattr(primitive, "height", getattr(aperture, "height", 0.0)) or 0.0)
            if w > 0 and h > 0:
                cx, cy = position[0], position[1]
                if w >= h:
                    r = h / 2.0
                    r_px = max(1, int(round(r * scale)))
                    c1 = mm_to_pixel(cx - (w / 2.0 - r), cy, bounds, scale, padding)
                    c2 = mm_to_pixel(cx + (w / 2.0 - r), cy, bounds, scale, padding)
                    p1 = mm_to_pixel(cx - (w / 2.0 - r), cy - r, bounds, scale, padding)
                    p2 = mm_to_pixel(cx + (w / 2.0 - r), cy + r, bounds, scale, padding)
                    _safe_rectangle(draw, p1, p2, fill)
                    draw.ellipse([(c1[0] - r_px, c1[1] - r_px), (c1[0] + r_px, c1[1] + r_px)], fill=fill)
                    draw.ellipse([(c2[0] - r_px, c2[1] - r_px), (c2[0] + r_px, c2[1] + r_px)], fill=fill)
                    if copper:
                        draw.ellipse([(c1[0] - r_px - 1, c1[1] - r_px - 1), (c1[0] + r_px + 1, c1[1] + r_px + 1)], outline=edge_fill, width=max(1, int(scale * 0.10)))
                        draw.ellipse([(c2[0] - r_px - 1, c2[1] - r_px - 1), (c2[0] + r_px + 1, c2[1] + r_px + 1)], outline=edge_fill, width=max(1, int(scale * 0.10)))
                else:
                    r = w / 2.0
                    r_px = max(1, int(round(r * scale)))
                    c1 = mm_to_pixel(cx, cy - (h / 2.0 - r), bounds, scale, padding)
                    c2 = mm_to_pixel(cx, cy + (h / 2.0 - r), bounds, scale, padding)
                    p1 = mm_to_pixel(cx - r, cy - (h / 2.0 - r), bounds, scale, padding)
                    p2 = mm_to_pixel(cx + r, cy + (h / 2.0 - r), bounds, scale, padding)
                    _safe_rectangle(draw, p1, p2, fill)
                    draw.ellipse([(c1[0] - r_px, c1[1] - r_px), (c1[0] + r_px, c1[1] + r_px)], fill=fill)
                    draw.ellipse([(c2[0] - r_px, c2[1] - r_px), (c2[0] + r_px, c2[1] + r_px)], fill=fill)
                    if copper:
                        draw.ellipse([(c1[0] - r_px - 1, c1[1] - r_px - 1), (c1[0] + r_px + 1, c1[1] + r_px + 1)], outline=edge_fill, width=max(1, int(scale * 0.10)))
                        draw.ellipse([(c2[0] - r_px - 1, c2[1] - r_px - 1), (c2[0] + r_px + 1, c2[1] + r_px + 1)], outline=edge_fill, width=max(1, int(scale * 0.10)))
                return 1

    # 6) Polygon / Region (Vertices)
    vertices = getattr(primitive, "vertices", getattr(primitive, "points", None))
    if vertices:
        points = []
        for point in vertices:
            if len(point) >= 2:
                points.append(mm_to_pixel(point[0], point[1], bounds, scale, padding))
        if len(points) >= 3:
            draw.polygon(points, fill=fill)
            if copper:
                draw.line(points + [points[0]], fill=edge_fill, width=max(1, int(scale * 0.10)))
            return 1

    # 7) Flashed Primitive Fallback
    if position is not None:
        px, py = mm_to_pixel(position[0], position[1], bounds, scale, padding)
        dia = float(getattr(primitive, "diameter", getattr(aperture, "diameter", 0.0)) or 0.0)
        if dia > 0:
            radius = max(1, int(round(dia * scale / 2.0)))
            draw.ellipse([(px - radius, py - radius), (px + radius, py + radius)], fill=fill)
            if copper:
                draw.ellipse([(px - radius - 1, py - radius - 1), (px + radius + 1, py + radius + 1)], outline=edge_fill, width=max(1, int(scale * 0.10)))
            return 1

    return 0


def draw_layer(
    draw,
    file_path,
    bounds,
    scale,
    padding,
    fill,
    copper=False,
):
    """
    Render Gerber primitives.

    copper=True gives copper traces/pads a subtle dark edge and
    highlight so the result does not look like a flat brown blob.
    """
    g = _safe_read(file_path)

    if g is None:
        return 0

    count = 0
    edge_fill, highlight_fill = _copper_colors(fill)

    for primitive in getattr(g, "primitives", []):
        try:
            count += _draw_single_primitive(
                draw,
                primitive,
                bounds,
                scale,
                padding,
                fill,
                copper,
                edge_fill,
                highlight_fill,
            )
        except Exception as e:
            print(f"Primitive render error in {Path(file_path).name}: {e}")

    return count


# ============================================================
# OUTLINE RENDERING
# ============================================================

def _get_board_outline_shape(extracted_path, project_files, bounds, scale, padding):
    """
    Parse board outline file and return pixel geometry for round, polygon, or custom PCB shapes.
    """
    outline_path = _find_outline(extracted_path, project_files)
    if not outline_path or not outline_path.exists():
        return None

    def arc_to_points(primitive, step_degrees=2.0):
        center = getattr(primitive, "center", None)
        start = getattr(primitive, "start", None)
        end = getattr(primitive, "end", None)
        if center is None or start is None or end is None:
            return []
        try:
            cx, cy = float(center[0]), float(center[1])
            sx, sy = float(start[0]), float(start[1])
            ex, ey = float(end[0]), float(end[1])
        except Exception:
            return []
        r1 = math.hypot(sx - cx, sy - cy)
        r2 = math.hypot(ex - cx, ey - cy)
        if r1 <= 1e-12 or r2 <= 1e-12:
            return [(sx, sy), (ex, ey)]
        r = (r1 + r2) / 2.0
        a1 = math.atan2(sy - cy, sx - cx)
        a2 = math.atan2(ey - cy, ex - cx)
        direction = str(getattr(primitive, "direction", "counterclockwise")).lower()
        clockwise = ("clockwise" in direction and "counter" not in direction)
        if clockwise:
            sweep = a1 - a2
            while sweep < 0:
                sweep += 2 * math.pi
        else:
            sweep = a2 - a1
            while sweep < 0:
                sweep += 2 * math.pi
        if sweep < 1e-10:
            sweep = 2 * math.pi
        steps = max(4, int(math.ceil(sweep / math.radians(step_degrees))))
        pts = []
        for i in range(steps + 1):
            t = i / steps
            angle = (a1 - sweep * t) if clockwise else (a1 + sweep * t)
            pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        pts[0] = (sx, sy)
        pts[-1] = (ex, ey)
        return pts

    circles = []
    segments = []

    try:
        gf = gerber.read(str(outline_path))
        if str(getattr(gf, "units", "metric")).lower() == "inch":
            gf.to_metric()
    except Exception:
        gf = None

    if gf and getattr(gf, "primitives", None):
        def visit(p):
            p_name = type(p).__name__.lower()
            if "circle" in p_name:
                pos = getattr(p, "position", None) or getattr(p, "center", None)
                dia = getattr(p, "diameter", None) or (getattr(p, "radius", 0) * 2)
                if pos and dia and float(dia) > 2.0:
                    circles.append({"center": (float(pos[0]), float(pos[1])), "radius": float(dia) / 2.0})
            elif "region" in p_name and hasattr(p, "primitives"):
                for child in getattr(p, "primitives", []) or []:
                    visit(child)
            elif "arc" in p_name:
                pts = arc_to_points(p, step_degrees=2.0)
                if pts:
                    for i in range(len(pts) - 1):
                        segments.append((pts[i], pts[i+1]))
            elif hasattr(p, "start") and hasattr(p, "end"):
                try:
                    s = (float(p.start[0]), float(p.start[1]))
                    e = (float(p.end[0]), float(p.end[1]))
                    if math.hypot(s[0], s[1]) < 1e-4 and math.hypot(e[0], e[1]) > 1.0:
                        pass
                    else:
                        segments.append((s, e))
                except Exception:
                    pass

        for prim in gf.primitives:
            visit(prim)

    if circles:
        # Pick the circle closest to the board dimensions
        b_w = bounds.get("max_x", 0) - bounds.get("min_x", 0)
        b_h = bounds.get("max_y", 0) - bounds.get("min_y", 0)
        exp_r = max(b_w, b_h) / 2.0
        for c in circles:
            if exp_r > 0 and abs(c["radius"] - exp_r) / exp_r < 0.2:
                cx, cy = c["center"]
                r = c["radius"]
                cx_px, cy_px = mm_to_pixel(cx, cy, bounds, scale, padding)
                r_px = int(round(r * scale))
                return {
                    "type": "circle",
                    "center_px": (cx_px, cy_px),
                    "radius_px": r_px,
                    "bbox_px": [(cx_px - r_px, cy_px - r_px), (cx_px + r_px, cy_px + r_px)],
                }

    if segments:
        def poly_area(pts):
            area = 0
            for i in range(len(pts)):
                j = (i + 1) % len(pts)
                area += pts[i][0] * pts[j][1] - pts[j][0] * pts[i][1]
            return abs(area) / 2.0

        closed_loops = []
        rem = list(segments)

        while rem:
            chain = list(rem.pop(0))
            if math.hypot(chain[0][0] - chain[-1][0], chain[0][1] - chain[-1][1]) < 0.2:
                closed_loops.append(chain)
                continue

            guard = 0
            while guard < len(rem) + 20 and rem:
                guard += 1
                end = chain[-1]
                found = -1
                rev = False
                for i, (s, e) in enumerate(rem):
                    if math.hypot(s[0] - end[0], s[1] - end[1]) < 0.2:
                        found = i; rev = False; break
                    if math.hypot(e[0] - end[0], e[1] - end[1]) < 0.2:
                        found = i; rev = True; break
                if found < 0:
                    break
                part = list(rem.pop(found))
                if rev:
                    part.reverse()
                chain.extend(part[1:])
                if math.hypot(chain[0][0] - chain[-1][0], chain[0][1] - chain[-1][1]) < 0.2:
                    break

            if len(chain) >= 3:
                if math.hypot(chain[0][0] - chain[-1][0], chain[0][1] - chain[-1][1]) >= 0.2:
                    chain.append(chain[0])
                closed_loops.append(chain)

        if closed_loops:
            closed_loops.sort(key=lambda pts: poly_area(pts), reverse=True)
            best_pts = closed_loops[0]

            if len(best_pts) >= 8:
                xs = [p[0] for p in best_pts]
                ys = [p[1] for p in best_pts]
                cx = (min(xs) + max(xs)) / 2.0
                cy = (min(ys) + max(ys)) / 2.0
                radii = [math.hypot(p[0] - cx, p[1] - cy) for p in best_pts]
                avg_r = sum(radii) / len(radii)
                if avg_r > 2.0 and max(abs(r - avg_r) for r in radii) < 0.10 * avg_r:
                    cx_px, cy_px = mm_to_pixel(cx, cy, bounds, scale, padding)
                    r_px = int(round(avg_r * scale))
                    return {
                        "type": "circle",
                        "center_px": (cx_px, cy_px),
                        "radius_px": r_px,
                        "bbox_px": [(cx_px - r_px, cy_px - r_px), (cx_px + r_px, cy_px + r_px)],
                    }

            pixel_pts = [mm_to_pixel(x, y, bounds, scale, padding) for x, y in best_pts]
            return {
                "type": "polygon",
                "points_px": pixel_pts,
            }

    pts = _gerber_points(outline_path)
    if len(pts) >= 3:
        pixel_pts = [mm_to_pixel(x, y, bounds, scale, padding) for x, y, cmd in pts]
        return {
            "type": "polygon",
            "points_px": pixel_pts,
        }

    return None


def draw_board_outline(
    draw,
    extracted_path,
    project_files,
    bounds,
    scale,
    padding,
    fill=(12, 18, 14),
    width=2,
    shape=None,
):
    if shape is None:
        shape = _get_board_outline_shape(extracted_path, project_files, bounds, scale, padding)

    if shape:
        stype = shape.get("type")
        if stype == "circle":
            draw.ellipse(shape["bbox_px"], outline=fill, width=width)
            return 1
        elif stype == "polygon" and shape.get("points_px"):
            draw.polygon(shape["points_px"], outline=fill, width=width)
            return len(shape["points_px"])

    outline = _find_outline(
        extracted_path,
        project_files,
    )

    if outline is None:
        return 0

    points = _gerber_points(outline)

    if len(points) < 2:
        return 0

    previous = None
    count = 0

    for x, y, command in points:
        current = mm_to_pixel(
            x,
            y,
            bounds,
            scale,
            padding,
        )

        if command == "1" and previous is not None:
            _safe_line(
                draw,
                previous,
                current,
                fill,
                width,
            )
            count += 1

        previous = current

    return count


# ============================================================
# PROJECT FILE HELPERS
# ============================================================

def _items(project_files, layer):
    for item in project_files:
        if item.get("layer") == layer:
            yield item


def _drill_files(extracted_path, project_files):
    found = []
    if project_files:
        for item in project_files:
            l_str = str(item.get("layer", "")).lower()
            if item.get("category") == "drill" or ("drill" in l_str and "drawing" not in l_str and "map" not in l_str):
                filename = item.get("filename", "")
                p = Path(extracted_path) / filename
                if p.exists():
                    found.append(p)
    if not found:
        root = Path(extracted_path)
        for pattern in ("*.TXT", "*.txt", "*.DRL", "*.drl", "*.TAP", "*.tap", "*.XLN", "*.xln", "*.nc", "*.NC", "*drill*.gbr", "*Drill*.gbr", "*DRILL*.GBR"):
            for p in root.glob(pattern):
                name_upper = p.name.upper()
                if "REP" not in name_upper and "LDP" not in name_upper and "DRR" not in name_upper and "STATUS" not in name_upper and "MAP" not in name_upper and "DRAWING" not in name_upper:
                    found.append(p)
    return found


def _draw_named_layers(
    draw,
    extracted_path,
    project_files,
    layers,
    bounds,
    scale,
    padding,
    colors,
    copper_layers=None,
):
    copper_layers = set(copper_layers or [])

    drawn = False
    for layer in layers:
        for item in _items(project_files, layer):
            filename = item.get("filename", "")
            path = Path(extracted_path) / filename

            if not path.exists():
                continue

            draw_layer(
                draw,
                path,
                bounds,
                scale,
                padding,
                colors.get(layer, (100, 100, 100)),
                copper=layer in copper_layers,
            )
            drawn = True

    if not drawn and extracted_path:
        root = Path(extracted_path)
        for layer in layers:
            l_lower = layer.lower()
            patterns = []
            if "top copper" in l_lower or "top_copper" in l_lower or layer == "Top Copper":
                patterns = ["*copper_signal_top*", "*gtl*", "*top_copper*", "*top_signal*"]
            elif "bottom copper" in l_lower or "bottom_copper" in l_lower or layer == "Bottom Copper":
                patterns = ["*copper_signal_bot*", "*gbl*", "*bot_copper*", "*bottom_copper*"]
            elif "top soldermask" in l_lower or layer == "Top Soldermask":
                patterns = ["*soldermask_top*", "*gts*", "*top_mask*"]
            elif "bottom soldermask" in l_lower or layer == "Bottom Soldermask":
                patterns = ["*soldermask_bot*", "*gbs*", "*bot_mask*"]
            elif "top silkscreen" in l_lower or layer == "Top Silkscreen":
                patterns = ["*top_silk*", "*gto*"]
            elif "bottom silkscreen" in l_lower or layer == "Bottom Silkscreen":
                patterns = ["*bot_silk*", "*gbo*"]

            for pat in patterns:
                for p in root.glob(pat):
                    if p.is_file() and not p.name.startswith("."):
                        draw_layer(
                            draw,
                            p,
                            bounds,
                            scale,
                            padding,
                            colors.get(layer, (100, 100, 100)),
                            copper=layer in copper_layers,
                        )


def _draw_all_drills(
    draw,
    extracted_path,
    project_files,
    bounds,
    scale,
    padding,
    hole_fill=(15, 18, 16),
    ring_fill=None,
):
    total = 0

    for path in _drill_files(extracted_path, project_files):
        total += draw_drill_layer(
            draw,
            path,
            bounds,
            scale,
            padding,
            hole_fill=hole_fill,
            ring_fill=ring_fill,
        )

    return total


# ============================================================
# BOARD BASE
# ============================================================

def _board_rectangle(bounds, scale, padding):
    p1 = mm_to_pixel(
        bounds["min_x"],
        bounds["max_y"],
        bounds,
        scale,
        padding,
    )

    p2 = mm_to_pixel(
        bounds["max_x"],
        bounds["min_y"],
        bounds,
        scale,
        padding,
    )

    return [
        (
            min(p1[0], p2[0]),
            min(p1[1], p2[1]),
        ),
        (
            max(p1[0], p2[0]),
            max(p1[1], p2[1]),
        ),
    ]


def _draw_board_base(
    draw,
    board_rect,
    mask_exists=True,
    shape=None,
):
    """
    Realistic-ish FR4/solder-mask base.
    """
    if mask_exists:
        board_fill = (25, 112, 67)
    else:
        board_fill = (38, 73, 55)

    edge_color = (12, 61, 38)

    if shape:
        stype = shape.get("type")
        if stype == "circle":
            draw.ellipse(shape["bbox_px"], fill=board_fill, outline=edge_color, width=2)
            return
        elif stype == "polygon" and shape.get("points_px"):
            draw.polygon(shape["points_px"], fill=board_fill, outline=edge_color, width=2)
            return

    # Fallback to rectangle
    draw.rectangle(
        board_rect,
        fill=(28, 31, 29),
    )

    x1, y1 = board_rect[0]
    x2, y2 = board_rect[1]

    inset = max(2, int(min(x2 - x1, y2 - y1) * 0.008))

    inner = [
        (x1 + inset, y1 + inset),
        (x2 - inset, y2 - inset),
    ]

    draw.rectangle(
        inner,
        fill=board_fill,
    )

    draw.rectangle(
        inner,
        outline=edge_color,
        width=max(1, int(inset / 2)),
    )


def _has_layer(project_files, layer):
    return any(
        item.get("layer") == layer
        for item in project_files
    )


# ============================================================
# 2D TOP
# ============================================================

def _render_2d_top(
    extracted_path,
    project_files,
    bounds,
    scale,
    padding,
    width,
    height,
):
    shape = _get_board_outline_shape(
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
    )

    board_surface = Image.new(
        "RGB",
        (width, height),
        (244, 245, 244),
    )

    draw = ImageDraw.Draw(board_surface)

    board_rect = _board_rectangle(
        bounds,
        scale,
        padding,
    )

    _draw_board_base(
        draw,
        board_rect,
        mask_exists=_has_layer(
            project_files,
            "Top Solder Mask",
        ),
        shape=shape,
    )

    # Top copper ONLY.
    _draw_named_layers(
        draw,
        extracted_path,
        project_files,
        ["Top Copper"],
        bounds,
        scale,
        padding,
        {
            "Top Copper": (196, 118, 43),
        },
        copper_layers={"Top Copper"},
    )

    # Top silkscreen ONLY.
    _draw_named_layers(
        draw,
        extracted_path,
        project_files,
        ["Top Silkscreen"],
        bounds,
        scale,
        padding,
        {
            "Top Silkscreen": (242, 242, 238),
        },
    )

    # Drills last.
    _draw_all_drills(
        draw,
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        hole_fill=(8, 12, 10),
        ring_fill=(208, 183, 125),
    )

    draw_board_outline(
        draw,
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        fill=(5, 10, 7),
        width=max(2, int(scale * 0.16)),
        shape=shape,
    )

    if shape and shape.get("type") in ("circle", "polygon"):
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        if shape["type"] == "circle":
            mask_draw.ellipse(shape["bbox_px"], fill=255)
        elif shape["type"] == "polygon":
            mask_draw.polygon(shape["points_px"], fill=255)
        canvas = Image.new("RGB", (width, height), (244, 245, 244))
        canvas.paste(board_surface, (0, 0), mask)
        return canvas

    return board_surface


# ============================================================
# 2D BOTTOM
# ============================================================

def _render_2d_bottom(
    extracted_path,
    project_files,
    bounds,
    scale,
    padding,
    width,
    height,
):
    shape = _get_board_outline_shape(
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
    )

    board_surface = Image.new(
        "RGB",
        (width, height),
        (244, 245, 244),
    )

    draw = ImageDraw.Draw(board_surface)

    board_rect = _board_rectangle(
        bounds,
        scale,
        padding,
    )

    _draw_board_base(
        draw,
        board_rect,
        mask_exists=_has_layer(
            project_files,
            "Bottom Solder Mask",
        ),
        shape=shape,
    )

    # Bottom copper ONLY.
    _draw_named_layers(
        draw,
        extracted_path,
        project_files,
        ["Bottom Copper"],
        bounds,
        scale,
        padding,
        {
            "Bottom Copper": (184, 103, 38),
        },
        copper_layers={"Bottom Copper"},
    )

    # Bottom silkscreen ONLY.
    _draw_named_layers(
        draw,
        extracted_path,
        project_files,
        ["Bottom Silkscreen"],
        bounds,
        scale,
        padding,
        {
            "Bottom Silkscreen": (232, 232, 228),
        },
    )

    # Drills last.
    _draw_all_drills(
        draw,
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        hole_fill=(8, 12, 10),
        ring_fill=(208, 183, 125),
    )

    draw_board_outline(
        draw,
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        fill=(5, 10, 7),
        width=max(2, int(scale * 0.16)),
        shape=shape,
    )

    if shape and shape.get("type") in ("circle", "polygon"):
        mask = Image.new("L", (width, height), 0)
        mask_draw = ImageDraw.Draw(mask)
        if shape["type"] == "circle":
            mask_draw.ellipse(shape["bbox_px"], fill=255)
        elif shape["type"] == "polygon":
            mask_draw.polygon(shape["points_px"], fill=255)
        canvas = Image.new("RGB", (width, height), (244, 245, 244))
        canvas.paste(board_surface, (0, 0), mask)
        return canvas

    return board_surface


# ============================================================
# 3D-STYLE BOARD
# ============================================================

def _add_board_extrusion(
    surface,
    thickness=14,
    background=(235, 237, 235),
):
    """
    Creates a clean pseudo-3D board view from a rendered surface.

    This is deliberately a preview, not a CAD solid model.
    """
    sw, sh = surface.size

    canvas = Image.new(
        "RGB",
        (sw + thickness + 70, sh + thickness + 70),
        background,
    )

    # Soft shadow.
    shadow = Image.new(
        "RGBA",
        canvas.size,
        (0, 0, 0, 0),
    )

    shadow_draw = ImageDraw.Draw(shadow)

    shadow_draw.rounded_rectangle(
        [
            (40 + thickness, 30 + thickness),
            (
                40 + sw + thickness,
                30 + sh + thickness,
            ),
        ],
        radius=4,
        fill=(0, 0, 0, 70),
    )

    shadow = shadow.filter(
        ImageFilter.GaussianBlur(8)
    )

    canvas.paste(
        shadow,
        (0, 0),
        shadow,
    )

    # Board edge/extrusion.
    for i in range(thickness, 0, -1):
        edge = surface.copy()

        # Darken progressively toward the bottom.
        factor = 0.48 + (i / thickness) * 0.10
        edge = ImageEnhance.Brightness(edge).enhance(
            factor
        )

        canvas.paste(
            edge,
            (40 + i, 30 + i),
        )

    # Top/bottom visible surface.
    canvas.paste(
        surface,
        (40, 30),
    )

    # Clean outside frame.
    d = ImageDraw.Draw(canvas)

    d.rectangle(
        [
            (40, 30),
            (40 + sw, 30 + sh),
        ],
        outline=(12, 18, 14),
        width=2,
    )

    # Visible lower edge.
    d.line(
        [
            (40, 30 + sh),
            (
                40 + thickness,
                30 + sh + thickness,
            ),
            (
                40 + sw + thickness,
                30 + sh + thickness,
            ),
        ],
        fill=(17, 46, 30),
        width=3,
    )

    # Visible right edge.
    d.line(
        [
            (40 + sw, 30),
            (
                40 + sw + thickness,
                30 + thickness,
            ),
            (
                40 + sw + thickness,
                30 + sh + thickness,
            ),
        ],
        fill=(17, 46, 30),
        width=3,
    )

    return canvas


def _render_3d_top(surface):
    return _add_board_extrusion(
        surface,
        thickness=16,
        background=(232, 234, 232),
    )


def _render_3d_bottom(surface):
    return _add_board_extrusion(
        surface,
        thickness=16,
        background=(232, 234, 232),
    )


# ============================================================
# MAIN PREVIEW GENERATOR
# ============================================================

def generate_pcb_previews(
    project_path,
    extracted_path,
    project_files,
):
    """
    Generate all four PCB previews.

    Backward-compatible files:
        pcb_2d_preview.png  -> TOP 2D
        pcb_3d_preview.png  -> TOP 3D

    New files:
        pcb_top_2d.png
        pcb_bottom_2d.png
        pcb_top_3d.png
        pcb_bottom_3d.png
    """
    project_path = Path(project_path)
    extracted_path = Path(extracted_path)

    render_dir = (
        project_path / "renders"
    )

    render_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    bounds = get_board_bounds(
        extracted_path,
        project_files,
    )

    if not bounds:
        return {
            "success": False,
            "error": "Board outline not found.",
            "renders": [],
        }

    width_mm = (
        bounds["max_x"] -
        bounds["min_x"]
    )

    height_mm = (
        bounds["max_y"] -
        bounds["min_y"]
    )

    # High enough resolution for normal DFM viewing.
    scale = 12
    padding = 50

    image_width = max(
        500,
        int(round(
            width_mm * scale
            + padding * 2
        )),
    )

    image_height = max(
        350,
        int(round(
            height_mm * scale
            + padding * 2
        )),
    )

    # --------------------------------------------------------
    # TOP 2D
    # --------------------------------------------------------
    top_2d = _render_2d_top(
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        image_width,
        image_height,
    )

    top_2d_path = (
        render_dir / "pcb_top_2d.png"
    )

    top_2d.save(
        top_2d_path,
        "PNG",
    )

    # Backward compatibility.
    legacy_2d_path = (
        render_dir / "pcb_2d_preview.png"
    )

    top_2d.save(
        legacy_2d_path,
        "PNG",
    )

    # --------------------------------------------------------
    # BOTTOM 2D
    # --------------------------------------------------------
    bottom_2d = _render_2d_bottom(
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        image_width,
        image_height,
    )

    bottom_2d_path = (
        render_dir / "pcb_bottom_2d.png"
    )

    bottom_2d.save(
        bottom_2d_path,
        "PNG",
    )

    # --------------------------------------------------------
    # TOP 3D
    # --------------------------------------------------------
    top_3d = _render_3d_top(
        top_2d,
    )

    top_3d_path = (
        render_dir / "pcb_top_3d.png"
    )

    top_3d.save(
        top_3d_path,
        "PNG",
    )

    # Backward compatibility.
    legacy_3d_path = (
        render_dir / "pcb_3d_preview.png"
    )

    top_3d.save(
        legacy_3d_path,
        "PNG",
    )

    # --------------------------------------------------------
    # BOTTOM 3D
    # --------------------------------------------------------
    bottom_3d = _render_3d_bottom(
        bottom_2d,
    )

    bottom_3d_path = (
        render_dir / "pcb_bottom_3d.png"
    )

    bottom_3d.save(
        bottom_3d_path,
        "PNG",
    )

    # --------------------------------------------------------
    # DRILL COUNT
    # --------------------------------------------------------
    drill_count = 0

    for path in _drill_files(extracted_path, project_files):
        if path.exists():
            drill_count += len(
                _parse_excellon_drill(path)
            )

    return {
        "success": True,

        "board_size_mm": {
            "width": round(width_mm, 4),
            "height": round(height_mm, 4),
        },

        "drill_hits_rendered": drill_count,

        # Explicit paths for the new viewer.
        "preview_top_2d": str(top_2d_path),
        "preview_bottom_2d": str(bottom_2d_path),
        "preview_top_3d": str(top_3d_path),
        "preview_bottom_3d": str(bottom_3d_path),

        "renders": [
            {
                "name": "2D Top View",
                "side": "top",
                "dimension": "2d",
                "path": str(top_2d_path),
            },
            {
                "name": "2D Bottom View",
                "side": "bottom",
                "dimension": "2d",
                "path": str(bottom_2d_path),
            },
            {
                "name": "3D Top View",
                "side": "top",
                "dimension": "3d",
                "path": str(top_3d_path),
            },
            {
                "name": "3D Bottom View",
                "side": "bottom",
                "dimension": "3d",
                "path": str(bottom_3d_path),
            },

            # Legacy entries kept so the current main.py continues
            # to find a 2D and 3D preview.
            {
                "name": "2D PCB Preview",
                "side": "top",
                "dimension": "2d",
                "path": str(legacy_2d_path),
            },
            {
                "name": "3D PCB Preview",
                "side": "top",
                "dimension": "3d",
                "path": str(legacy_3d_path),
            },
        ],
    }


__all__ = [
    "get_board_bounds",
    "draw_layer",
    "draw_drill_layer",
    "draw_board_outline",
    "generate_pcb_previews",
]
