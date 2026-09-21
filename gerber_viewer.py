# ============================================================
# GERBER VECTOR VIEWER
# Accurate Gerber geometry -> browser JSON
# ============================================================

from pathlib import Path
import math
import re
import gerber
from nc_drill_parser import parse_headerless_nc_drill


# ============================================================
# BASIC HELPERS
# ============================================================

def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def _aperture_val(primitive, attr, default=0.0):
    val = getattr(primitive, attr, None)
    if val is not None:
        try:
            fval = float(val)
            if fval != 0.0:
                return fval
        except (ValueError, TypeError):
            pass
    ap = getattr(primitive, "aperture", None)
    if ap is not None:
        val = getattr(ap, attr, None)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
    return default



def _point(value):
    if value is None:
        return [0.0, 0.0]
    try:
        return [float(value[0]), float(value[1])]
    except Exception:
        pass
    try:
        return [float(value.x), float(value.y)]
    except Exception:
        return [0.0, 0.0]


def _get(obj, name, default=None):
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


def _primitive_name(primitive):
    return primitive.__class__.__name__.lower()


def _polarity(primitive):
    return str(
        _get(
            primitive,
            "polarity",
            _get(primitive, "level_polarity", "dark")
        )
    ).lower()


def _width(primitive):
    width = _get(primitive, "width", 0.0)
    if width:
        return _num(width, 0.0)

    aperture = _get(primitive, "aperture")
    if aperture is not None:
        return _num(_get(aperture, "diameter", 0.0), 0.0)

    return 0.0


# ============================================================
# ARC -> POLYLINE
# ============================================================

def _convert_arc(primitive, max_step_degrees=2.0):
    """
    Flatten a pcb-tools Arc to a deterministic polyline.

    pcb-tools already resolves the Gerber I/J center and direction.
    The browser therefore receives only ordinary Cartesian points.
    This avoids screen-space arc-direction/Y-axis bugs.
    """
    center = _point(_get(primitive, "center"))
    start = _point(_get(primitive, "start"))
    end = _point(_get(primitive, "end"))

    width = _width(primitive)
    direction = str(
        _get(primitive, "direction", "counterclockwise")
    ).lower()

    cx, cy = center
    sx, sy = start
    ex, ey = end

    r1 = math.hypot(sx - cx, sy - cy)
    r2 = math.hypot(ex - cx, ey - cy)

    if r1 <= 1e-12 or r2 <= 1e-12:
        return {
            "type": "polyline",
            "points": [start, end],
            "width": width,
            "polarity": _polarity(primitive),
        }

    radius = (r1 + r2) / 2.0
    a1 = math.atan2(sy - cy, sx - cx)
    a2 = math.atan2(ey - cy, ex - cx)

    clockwise = (
        "clockwise" in direction
        and "counter" not in direction
    )

    if clockwise:
        sweep = a1 - a2
        while sweep < 0:
            sweep += 2.0 * math.pi
    else:
        sweep = a2 - a1
        while sweep < 0:
            sweep += 2.0 * math.pi

    # pcb-tools can represent a full circle with identical endpoints.
    if sweep < 1e-10:
        sweep = 2.0 * math.pi

    steps = max(
        2,
        int(math.ceil(
            abs(sweep) / math.radians(max_step_degrees)
        ))
    )

    points = []
    for i in range(steps + 1):
        t = i / steps
        angle = (
            a1 - sweep * t
            if clockwise
            else a1 + sweep * t
        )
        points.append([
            cx + radius * math.cos(angle),
            cy + radius * math.sin(angle),
        ])

    points[0] = start
    points[-1] = end

    return {
        "type": "polyline",
        "points": points,
        "width": width,
        "polarity": _polarity(primitive),
    }


# ============================================================
# LINE
# ============================================================

def _convert_line(primitive):
    return {
        "type": "line",
        "start": _point(_get(primitive, "start")),
        "end": _point(_get(primitive, "end")),
        "width": _width(primitive),
        "polarity": _polarity(primitive),
    }


# ============================================================
# CIRCLE / FLASH
# ============================================================

def _convert_circle(primitive):
    position = _get(primitive, "position")
    if position is None:
        position = _get(primitive, "center")

    dia = _aperture_val(primitive, "diameter", 0.0)

    return {
        "type": "circle",
        "center": _point(position),
        "diameter": dia,
        "hole_diameter": _aperture_val(primitive, "hole_diameter", 0.0),
        "polarity": _polarity(primitive),
    }


# ============================================================
# RECTANGLE
# ============================================================

def _convert_rectangle(primitive):
    pos = _get(primitive, "position")
    if pos is None:
        pos = _get(primitive, "center")

    w = _aperture_val(primitive, "width", 0.0)
    h = _aperture_val(primitive, "height", 0.0)

    return {
        "type": "rectangle",
        "position": _point(pos),
        "width": w,
        "height": h,
        "rotation": _aperture_val(primitive, "rotation", 0.0),
        "polarity": _polarity(primitive),
    }


# ============================================================
# OBRROUND
# ============================================================

def _convert_obround(primitive):
    pos = _get(primitive, "position")
    if pos is None:
        pos = _get(primitive, "center")

    w = _aperture_val(primitive, "width", 0.0)
    h = _aperture_val(primitive, "height", 0.0)

    return {
        "type": "obround",
        "position": _point(pos),
        "width": w,
        "height": h,
        "rotation": _aperture_val(primitive, "rotation", 0.0),
        "polarity": _polarity(primitive),
    }


def _convert_polygon_vertices(primitive):
    vertices = _get(primitive, "vertices")
    if vertices is None:
        return None
    try:
        points = [_point(v) for v in vertices]
    except Exception:
        return None
    if len(points) < 3:
        return None
    return {
        "type": "polygon",
        "points": points,
        "polarity": _polarity(primitive),
    }


def _convert_round_rectangle(primitive, steps_per_corner=8):
    """
    Convert pcb-tools RoundRectangle macro flashes into a polygon.
    KiCad custom RoundRect aperture macros otherwise disappear.
    """
    pos = _point(_get(primitive, "position"))
    w = abs(_num(_get(primitive, "width", 0.0)))
    h = abs(_num(_get(primitive, "height", 0.0)))
    radius = max(0.0, _num(_get(primitive, "radius", 0.0)))
    rotation = math.radians(_num(_get(primitive, "rotation", 0.0)))

    if w <= 0 or h <= 0:
        return None

    radius = min(radius, w / 2.0, h / 2.0)
    corners = list(_get(primitive, "corners", [True, True, True, True]) or [])
    while len(corners) < 4:
        corners.append(True)

    cx, cy = pos
    hw, hh = w / 2.0, h / 2.0
    centers = [
        (cx + hw - radius, cy + hh - radius),
        (cx - hw + radius, cy + hh - radius),
        (cx - hw + radius, cy - hh + radius),
        (cx + hw - radius, cy - hh + radius),
    ]
    ranges = [
        (0.0, math.pi / 2.0),
        (math.pi / 2.0, math.pi),
        (math.pi, 3.0 * math.pi / 2.0),
        (3.0 * math.pi / 2.0, 2.0 * math.pi),
    ]

    def rotate(x, y):
        dx, dy = x - cx, y - cy
        co, si = math.cos(rotation), math.sin(rotation)
        return [
            cx + dx * co - dy * si,
            cy + dx * si + dy * co,
        ]

    pts = []
    square = [
        (cx + hw, cy + hh),
        (cx - hw, cy + hh),
        (cx - hw, cy - hh),
        (cx + hw, cy - hh),
    ]

    for idx, ((ccx, ccy), (a0, a1)) in enumerate(zip(centers, ranges)):
        if corners[idx] and radius > 0:
            for j in range(steps_per_corner + 1):
                a = a0 + (a1 - a0) * j / steps_per_corner
                pts.append(rotate(
                    ccx + radius * math.cos(a),
                    ccy + radius * math.sin(a),
                ))
        else:
            pts.append(rotate(*square[idx]))

    return {
        "type": "polygon",
        "points": pts,
        "polarity": _polarity(primitive),
    }


# ============================================================
# REGION
# ============================================================

def _primitive_path(converted):
    if not converted:
        return None

    if converted["type"] == "line":
        return [
            converted["start"],
            converted["end"],
        ]

    if converted["type"] == "polyline":
        return converted.get("points", [])

    return None


def _connect_region_segments(segments, tol=1e-5):
    if not segments:
        return []
    segs = list(segments)
    paths = []
    while segs:
        current_path = [segs[0][0], segs[0][1]]
        segs.pop(0)
        changed = True
        while changed and segs:
            changed = False
            last_pt = current_path[-1]
            first_pt = current_path[0]
            for i, seg in enumerate(segs):
                p1, p2 = seg[0], seg[1]
                if math.hypot(p1[0] - last_pt[0], p1[1] - last_pt[1]) <= tol:
                    current_path.append(p2)
                    segs.pop(i)
                    changed = True
                    break
                elif math.hypot(p2[0] - last_pt[0], p2[1] - last_pt[1]) <= tol:
                    current_path.append(p1)
                    segs.pop(i)
                    changed = True
                    break
                elif math.hypot(p2[0] - first_pt[0], p2[1] - first_pt[1]) <= tol:
                    current_path.insert(0, p1)
                    segs.pop(i)
                    changed = True
                    break
                elif math.hypot(p1[0] - first_pt[0], p1[1] - first_pt[1]) <= tol:
                    current_path.insert(0, p2)
                    segs.pop(i)
                    changed = True
                    break
        if len(current_path) >= 3:
            if math.hypot(current_path[0][0] - current_path[-1][0], current_path[0][1] - current_path[-1][1]) > tol:
                current_path.append(current_path[0])
            paths.append(current_path)
    return paths


def _convert_region(primitive):
    """
    Convert region/outline primitives into closed polygon paths.
    """
    vertices = _get(primitive, "vertices", None)
    if vertices and len(vertices) >= 3:
        pts = [_point(v) for v in vertices]
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) > 1e-6:
            pts.append(pts[0])
        return {
            "type": "region",
            "paths": [pts],
            "polarity": _polarity(primitive),
        }

    segments = []
    for child in _get(primitive, "primitives", []) or []:
        converted = _convert_primitive(child)
        if not converted:
            continue
        if isinstance(converted, list):
            for c in converted:
                p = _primitive_path(c)
                if p and len(p) >= 2:
                    for k in range(len(p) - 1):
                        segments.append((p[k], p[k + 1]))
        else:
            p = _primitive_path(converted)
            if p and len(p) >= 2:
                for k in range(len(p) - 1):
                    segments.append((p[k], p[k + 1]))

    paths = _connect_region_segments(segments)

    return {
        "type": "region",
        "paths": paths,
        "polarity": _polarity(primitive),
    }


def _evaluate_amgroup(primitive):
    """
    Evaluates an AMGroup (Aperture Macro Flash) directly from its Gerber macro statements,
    bypassing pcb-tools' degree/radian rotation bug in Code 21 Center Rectangles and Outlines.
    """
    stmt = getattr(primitive, "stmt", None)
    stmt_prims = getattr(stmt, "primitives", None) if stmt else None
    if not stmt_prims:
        return None

    am_x, am_y = getattr(primitive, "position", (0.0, 0.0))
    am_rot = float(getattr(primitive, "rotation", 0.0) or 0.0)
    am_rot_rad = math.radians(am_rot)

    def transform_pt(px, py):
        gx = am_x + px * math.cos(am_rot_rad) - py * math.sin(am_rot_rad)
        gy = am_y + px * math.sin(am_rot_rad) + py * math.cos(am_rot_rad)
        return [round(gx, 6), round(gy, 6)]

    converted = []
    for p in stmt_prims:
        p_name = type(p).__name__
        exp = getattr(p, "exposure", "on")
        pol = "dark" if exp == "on" else "clear"

        if p_name == "AMCenterLinePrimitive":  # Code 21 Center Rectangle
            hw, hh = p.width / 2.0, p.height / 2.0
            rot_rad = math.radians(getattr(p, "rotation", 0.0) or 0.0)
            cx, cy = getattr(p, "center", (0.0, 0.0))
            corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
            pts = []
            for dx, dy in corners:
                rx = cx + dx * math.cos(rot_rad) - dy * math.sin(rot_rad)
                ry = cy + dx * math.sin(rot_rad) + dy * math.cos(rot_rad)
                pts.append(transform_pt(rx, ry))
            pts.append(pts[0])
            converted.append({"type": "region", "paths": [pts], "polarity": pol})

        elif p_name == "AMLowerLeftLinePrimitive":  # Code 22 Lower Left Rectangle
            w, h = p.width, p.height
            rot_rad = math.radians(getattr(p, "rotation", 0.0) or 0.0)
            lx, ly = getattr(p, "lower_left", (0.0, 0.0))
            corners = [(0, 0), (w, 0), (w, h), (0, h)]
            pts = []
            for dx, dy in corners:
                rx = lx + dx * math.cos(rot_rad) - dy * math.sin(rot_rad)
                ry = ly + dx * math.sin(rot_rad) + dy * math.cos(rot_rad)
                pts.append(transform_pt(rx, ry))
            pts.append(pts[0])
            converted.append({"type": "region", "paths": [pts], "polarity": pol})

        elif p_name == "AMCirclePrimitive":  # Code 1 Circle
            dia = getattr(p, "diameter", 0.0)
            cx, cy = getattr(p, "position", getattr(p, "center", (0.0, 0.0)))
            if dia > 0:
                center_pt = transform_pt(cx, cy)
                converted.append({"type": "circle", "center": center_pt, "diameter": dia, "polarity": pol})

        elif p_name == "AMOutlinePrimitive":  # Code 4 Outline Polygon
            start = getattr(p, "start_point", (0.0, 0.0))
            pts_raw = [start] + list(getattr(p, "points", []))
            rot_rad = math.radians(getattr(p, "rotation", 0.0) or 0.0)
            poly_pts = []
            for px, py in pts_raw:
                rx = px * math.cos(rot_rad) - py * math.sin(rot_rad)
                ry = px * math.sin(rot_rad) + py * math.cos(rot_rad)
                poly_pts.append(transform_pt(rx, ry))
            if poly_pts and poly_pts[0] != poly_pts[-1]:
                poly_pts.append(poly_pts[0])
            if len(poly_pts) >= 3:
                converted.append({"type": "region", "paths": [poly_pts], "polarity": pol})

        elif p_name == "AMPolygonPrimitive":  # Code 5 Polygon
            n_sides = int(getattr(p, "number_of_vertices", 0))
            cx, cy = getattr(p, "position", (0.0, 0.0))
            dia = getattr(p, "diameter", 0.0)
            rot_rad = math.radians(getattr(p, "rotation", 0.0) or 0.0)
            if n_sides >= 3 and dia > 0:
                rad = dia / 2.0
                step = 2.0 * math.pi / n_sides
                poly_pts = []
                for i in range(n_sides):
                    angle = rot_rad + i * step
                    rx = cx + rad * math.cos(angle)
                    ry = cy + rad * math.sin(angle)
                    poly_pts.append(transform_pt(rx, ry))
                poly_pts.append(poly_pts[0])
                converted.append({"type": "region", "paths": [poly_pts], "polarity": pol})

    return converted if converted else None


# ============================================================
# GENERIC PRIMITIVE
# ============================================================

def _convert_primitive(primitive):
    if primitive is None:
        return None

    name = _primitive_name(primitive)

    # Aperture macro groups & aperture instances are collections of real primitives.
    if name in {"amgroup", "aperturemacro", "macrogroup", "aperturemacroinstance"} or (hasattr(primitive, "primitives") and "region" not in name and name != "outline"):
        evaluated = _evaluate_amgroup(primitive)
        if evaluated:
            return evaluated
        children = (
            _get(primitive, "primitives", None) or
            _get(_get(primitive, "aperture"), "primitives", None) or
            _get(_get(_get(primitive, "aperture"), "macro"), "primitives", None) or
            _get(primitive, "statements", None)
        )
        if children:
            out = []
            for child in children:
                converted = _convert_primitive(child)
                if isinstance(converted, list):
                    out.extend(p for p in converted if p)
                elif converted:
                    out.append(converted)
            if out:
                return out

    if "region" in name or name == "outline":
        try:
            return _convert_region(primitive)
        except Exception:
            return None

    if "arc" in name and hasattr(primitive, "center"):
        return _convert_arc(primitive)

    if "line" in name or (
        hasattr(primitive, "start")
        and hasattr(primitive, "end")
        and not hasattr(primitive, "center")
    ):
        return _convert_line(primitive)

    if "roundrectangle" in name or "round_rectangle" in name:
        return _convert_round_rectangle(primitive)

    if "chamferrectangle" in name or "chamfer_rectangle" in name:
        return _convert_polygon_vertices(primitive)

    if name in {"diamond", "polygon"}:
        return _convert_polygon_vertices(primitive)

    aperture = _get(primitive, "aperture")
    ap_name = _primitive_name(aperture) if aperture else ""

    if "circle" in name or "circle" in ap_name or (
        (hasattr(primitive, "position") or hasattr(primitive, "center"))
        and (_get(primitive, "diameter") is not None or _get(aperture, "diameter") is not None)
    ):
        return _convert_circle(primitive)

    if "rectangle" in name or "rectangle" in ap_name:
        return _convert_rectangle(primitive)

    if "obround" in name or "oval" in name or "oblong" in name or "obround" in ap_name:
        return _convert_obround(primitive)

    # Generic flashed primitive with vertices.
    if _get(primitive, "position") is not None:
        converted = _convert_polygon_vertices(primitive)
        if converted:
            return converted

    position = _get(primitive, "position")
    if position is None:
        position = _get(primitive, "center")
    if position is not None:
        diameter = _aperture_val(primitive, "diameter", 0.0)
        if diameter > 0:
            return {
                "type": "flash",
                "position": _point(position),
                "diameter": diameter,
                "polarity": _polarity(primitive),
            }

    return None


# ============================================================
# BOUNDS
# ============================================================

def _point_bounds(points):
    if not points:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    return {
        "x_min": min(xs),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
    }


def _collect_bounds_from_converted(p, xs, ys):
    if not p:
        return

    typ = p.get("type")

    if typ == "line":
        for point in (p.get("start"), p.get("end")):
            if point:
                xs.append(point[0])
                ys.append(point[1])

    elif typ == "polyline":
        for point in p.get("points", []):
            xs.append(point[0])
            ys.append(point[1])

        # Stroke width contributes to the actual visual bounds.
        width = p.get("width", 0.0) or 0.0
        if width > 0 and p.get("points"):
            r = width / 2.0
            for point in p["points"]:
                xs.extend([point[0] - r, point[0] + r])
                ys.extend([point[1] - r, point[1] + r])

    elif typ == "circle":
        c = p.get("center", [0, 0])
        r = abs(p.get("diameter", 0.0)) / 2.0
        xs.extend([c[0] - r, c[0] + r])
        ys.extend([c[1] - r, c[1] + r])

    elif typ == "drill":
        c = p.get("center", [0, 0])
        r = abs(p.get("diameter", 0.0)) / 2.0
        xs.extend([c[0] - r, c[0] + r])
        ys.extend([c[1] - r, c[1] + r])

    elif typ == "rectangle":
        x, y = p.get("position", [0, 0])
        w = abs(p.get("width", 0.0)) / 2.0
        h = abs(p.get("height", 0.0)) / 2.0
        a = math.radians(p.get("rotation", 0.0))
        ca, sa = math.cos(a), math.sin(a)
        for sx, sy in [(-w,-h), (w,-h), (w,h), (-w,h)]:
            xs.append(x + sx * ca - sy * sa)
            ys.append(y + sx * sa + sy * ca)

    elif typ == "obround":
        x, y = p.get("position", [0, 0])
        w = abs(p.get("width", 0.0))
        h = abs(p.get("height", 0.0))
        r = min(w, h) / 2.0
        # Conservative rotated bound; exact shape rendering is done in JS.
        a = math.radians(p.get("rotation", 0.0))
        ca, sa = math.cos(a), math.sin(a)
        for px, py in [
            (-w/2, -h/2), (w/2, -h/2),
            (w/2, h/2), (-w/2, h/2)
        ]:
            xs.append(x + px * ca - py * sa)
            ys.append(y + px * sa + py * ca)

    elif typ == "region":
        for path in p.get("paths", []):
            for point in path:
                xs.append(point[0])
                ys.append(point[1])

    elif typ == "flash":
        c = p.get("position", [0, 0])
        r = abs(p.get("diameter", 0.0)) / 2.0
        xs.extend([c[0] - r, c[0] + r])
        ys.extend([c[1] - r, c[1] + r])


def _geometry_bounds(primitives):
    xs = []
    ys = []

    for primitive in primitives:
        _collect_bounds_from_converted(
            primitive,
            xs,
            ys
        )

    if not xs or not ys:
        return None

    return {
        "x_min": min(xs),
        "x_max": max(xs),
        "y_min": min(ys),
        "y_max": max(ys),
        "width_mm": max(xs) - min(xs),
        "height_mm": max(ys) - min(ys),
        "area_mm2": (max(xs) - min(xs)) * (max(ys) - min(ys)),
    }


# ============================================================
# READ GERBER
# ============================================================

def read_gerber_geometry(file_path):
    file_path = Path(file_path)

    try:
        gerber_file = gerber.read(str(file_path))

        if str(
            getattr(
                gerber_file,
                "units",
                "metric"
            )
        ).lower() == "inch":
            gerber_file.to_metric()

    except Exception as e:
        return {
            "filename": file_path.name,
            "primitives": [],
            "bounds": None,
            "primitive_errors": 0,
            "error": str(e),
        }

    primitives = []
    primitive_errors = 0

    for primitive in getattr(
        gerber_file,
        "primitives",
        []
    ):
        try:
            converted = _convert_primitive(
                primitive
            )
            if isinstance(converted, list):
                primitives.extend(
                    p for p in converted
                    if p is not None
                )
            elif converted:
                primitives.append(converted)
        except Exception:
            primitive_errors += 1

    # Filter out spurious initial (0,0) line created by gerber.read's default initial state
    if primitives:
        p0 = primitives[0]
        if isinstance(p0, dict) and p0.get("type") == "line" and p0.get("start"):
            sx, sy = p0["start"]
            ex, ey = p0.get("end", (0, 0))
            if math.hypot(sx, sy) < 1e-4 and math.hypot(ex, ey) > 1.0:
                primitives.pop(0)

    return {
        "filename": file_path.name,
        "primitives": primitives,
        "bounds": _geometry_bounds(primitives),
        "primitive_errors": primitive_errors,
        "source_info": _detect_gerber_source_info(file_path),
    }


# ============================================================
# LAYER ORDER / NORMALIZATION
# ============================================================

_LAYER_ORDER = {
    "Board Outline": 0,
    "Drill": 5,
    "PTH Drill": 6,
    "NPTH Drill": 7,
    "Drill Drawing": 8,
    "Bottom Copper": 10,
    "Inner Copper": 15,
    "Top Copper": 20,
    "Bottom Solder Mask": 30,
    "Top Solder Mask": 40,
    "Bottom Silkscreen": 50,
    "Top Silkscreen": 60,
}

def _normalize_layer(item, file_path=None):
    """Use the layer already determined by main.py/global classifier.

    The viewer deliberately does not re-read/reclassify files here. This
    avoids a second full text scan for every layer and prevents viewer-side
    classification drift.
    """
    return str(item.get("layer") or "Other Gerber")

def _layer_sort(item):
    layer = item.get("layer", "")
    if layer in _LAYER_ORDER:
        return _LAYER_ORDER[layer]
    if str(layer).lower().startswith("inner") and "copper" in str(layer).lower():
        return 15
    return 100


# ============================================================
# SOURCE-FORMAT DETECTION
# ============================================================

def _detect_gerber_source_info(file_path):
    """Inspect the Gerber header independently of pcb-tools.

    Geometry is still parsed by pcb-tools; this metadata records what the
    actual source file declares so Gerber unit/format assumptions never leak
    into Excellon parsing.
    """
    try:
        text = Path(file_path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = ""
    upper = text.upper()
    units = "inch" if re.search(r"%MO(IN|INCH)\*%", upper) else "metric" if re.search(r"%MO(MM|METRIC)\*%", upper) else "unknown"
    fm = re.search(r"%FS[^%]*?X(\d)(\d)Y(\d)(\d)\*%", upper)
    fmt = f"{fm.group(1)}:{fm.group(2)}" if fm else None
    zero = None
    if fm:
        z = fm.group(1).upper()
        zero = {"L": "leading", "T": "trailing"}.get(z, "none")
    polarity = None
    lp = re.search(r"%LP([DC])\*%", upper)
    if lp:
        polarity = "dark" if lp.group(1) == "D" else "clear"
    return {
        "file_type": "Gerber",
        "source_units": units,
        "coordinate_format": fmt,
        "zero_suppression": zero,
        "layer_polarity": polarity,
        "normalized_units": "mm",
    }


# ============================================================
# EXCELLON / NC DRILL READER
# ============================================================

def _normalize_tool_id(value):
    m = re.match(r"^T(\d+)$", str(value or "").strip().upper())
    return f"T{int(m.group(1))}" if m else str(value or "").strip().upper()


def _detect_excellon_source_info(text):
    """Detect Excellon units/format/zero suppression from the file itself."""
    upper = text.upper()
    units = "inch" if re.search(r"\bINCH(?:,|\s|$)", upper) else "metric" if re.search(r"\bMETRIC(?:,|\s|$)", upper) else "unknown"

    zero = None
    if re.search(r"(?:^|[,\s])LZ(?:[,\s]|$)", upper, re.M):
        zero = "leading"
    elif re.search(r"(?:^|[,\s])TZ(?:[,\s]|$)", upper, re.M):
        zero = "trailing"

    fmt = None
    # Modern comments often say FILE_FORMAT=4:4; legacy Excellon uses FMAT.
    m = re.search(r"FILE[_ ]?FORMAT\s*=\s*(\d+)\s*[:.]\s*(\d+)", upper)
    if m:
        fmt = f"{m.group(1)}:{m.group(2)}"
    else:
        m = re.search(r"FMAT\s*,?\s*(\d+)(?:\s*[:.]\s*(\d+))?", upper)
        if m:
            fmt = f"{m.group(1)}:{m.group(2) or '4'}"
    if fmt is None:
        fmt = "2:4"

    return {
        "file_type": "Excellon",
        "source_units": units,
        "coordinate_format": fmt,
        "zero_suppression": zero,
        "normalized_units": "mm",
    }


def _format_decimals(integer_format):
    if not integer_format:
        return 4
    m = re.match(r"^\s*\d+\s*[:.]\s*(\d+)\s*$", str(integer_format))
    return int(m.group(1)) if m else 4


def _format_int_digits(integer_format):
    if not integer_format:
        return 2
    m = re.match(r"^\s*(\d+)\s*[:.]\s*\d+\s*$", str(integer_format))
    return int(m.group(1)) if m else 2


def _parse_excellon_number(token, units, zero_suppression, integer_format, is_coordinate=False):
    """Parse one Excellon value, then normalize it to mm.

    Explicit decimal values are interpreted as already decimal-valued. Fixed
    integer coordinates handle Leading Zero Suppression (LZ) and Trailing Zero
    Suppression (TZ) based on file header declarations.
    """
    if token is None or token == "":
        return None
    token = str(token).strip()
    try:
        if "." in token:
            value = float(token)
        else:
            sign = -1.0 if token.startswith("-") else 1.0
            digits = token.lstrip("+-")
            if not digits.isdigit():
                return None
            zero_supp = str(zero_suppression or "").lower()
            if zero_supp in {"leading", "lz"} and is_coordinate:
                int_digits = _format_int_digits(integer_format)
                if len(digits) <= int_digits:
                    value = float(digits)
                else:
                    int_part = digits[:int_digits]
                    dec_part = digits[int_digits:]
                    value = float(int_part) + float(dec_part) / (10 ** len(dec_part))
            else:
                value = int(digits) / (10 ** _format_decimals(integer_format))
            value *= sign
    except (ValueError, TypeError):
        return None
    if units == "inch":
        value *= 25.4
    return value


def read_excellon_geometry(file_path):
    """Read common Excellon variants independently from Gerber settings."""
    file_path = Path(file_path)

    try:
        legacy = parse_headerless_nc_drill(file_path)
    except Exception as legacy_err:
        legacy = None

    if legacy is not None and legacy.get("primitives"):
        return {
            "filename": file_path.name,
            "primitives": legacy.get("primitives", []),
            "bounds": legacy.get("bounds"),
            "primitive_errors": 0,
            "tools": legacy.get("tools", []),
            "drill_count": legacy.get("drill_count", 0),
            "source_info": legacy.get("source_info", {}),
            "method": "legacy_headerless_tap",
        }

    try:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return {"filename": file_path.name, "primitives": [], "bounds": None, "error": str(e)}

    info = _detect_excellon_source_info(text)
    units = info["source_units"] if info["source_units"] != "unknown" else "metric"
    zero = info["zero_suppression"] or "leading"
    fmt = info["coordinate_format"] or "2:4"

    tools = {}
    current_tool = None
    primitives = []
    x_current = None
    y_current = None
    parse_errors = 0

    # T01C0.800, T01F00S00C0.5000, etc. F/S fields are optional.
    tool_def_re = re.compile(
        r"^\s*(T\d+)"
        r"(?:F[+-]?\d+(?:\.\d+)?)?"
        r"(?:S[+-]?\d+(?:\.\d+)?)?"
        r"C\s*([+-]?\d+(?:\.\d+)?)",
        re.I,
    )

    for raw in text.splitlines():
        line = raw.strip().upper()
        if not line or line.startswith(";"):
            continue

        td = tool_def_re.match(line)
        if td:
            tool = _normalize_tool_id(td.group(1))
            # Tool diameter is explicit decimal when C contains a decimal.
            dia = _parse_excellon_number(td.group(2), units, zero, fmt, False)
            if dia is not None and dia > 0:
                tools[tool] = dia
            continue

        ts = re.match(r"^T(\d+)\s*$", line)
        if ts:
            current_tool = _normalize_tool_id("T" + ts.group(1))
            continue

        if current_tool is None or current_tool not in tools:
            continue
        if line.startswith("M") and not ("X" in line or "Y" in line):
            continue

        xm = re.search(r"X([+-]?\d+(?:\.\d+)?)", line)
        ym = re.search(r"Y([+-]?\d+(?:\.\d+)?)", line)

        # Require both X and Y on drill hit lines to prevent spurious horizontal dots
        if not (xm and ym):
            try:
                if xm:
                    x_current = _parse_excellon_number(xm.group(1), units, zero, fmt, True)
                if ym:
                    y_current = _parse_excellon_number(ym.group(1), units, zero, fmt, True)
            except Exception:
                pass
            continue

        try:
            x_current = _parse_excellon_number(xm.group(1), units, zero, fmt, True)
            y_current = _parse_excellon_number(ym.group(1), units, zero, fmt, True)
        except Exception:
            parse_errors += 1
            continue

        if x_current is None or y_current is None:
            continue

        primitives.append({
            "type": "drill",
            "center": [x_current, y_current],
            "diameter": tools[current_tool],
            "tool": current_tool,
            "polarity": "dark",
        })

    if not primitives:
        try:
            gerber_res = read_gerber_geometry(file_path)
            gerber_prims = gerber_res.get("primitives", []) if gerber_res else []
            if gerber_prims:
                converted_prims = []
                gerber_tools = {}
                for idx, p in enumerate(gerber_prims):
                    ptype = p.get("type")
                    center = p.get("center") or p.get("position")
                    dia = p.get("diameter", 0.0)
                    if not dia and ptype == "circle":
                        dia = p.get("width", 0.0)
                    if ptype in ("circle", "drill", "flash", "pad") and center and dia > 0:
                        tool_name = f"T{idx+1:02d}"
                        converted_prims.append({
                            "type": "drill",
                            "center": center,
                            "diameter": dia,
                            "tool": tool_name,
                            "polarity": p.get("polarity", "dark"),
                        })
                        gerber_tools[tool_name] = dia

                if converted_prims:
                    xs, ys = [], []
                    for p in converted_prims:
                        x, y = p["center"]
                        r = p["diameter"] / 2.0
                        xs.extend((x - r, x + r))
                        ys.extend((y - r, y + r))
                    bounds = {
                        "x_min": min(xs),
                        "x_max": max(xs),
                        "y_min": min(ys),
                        "y_max": max(ys),
                        "width_mm": max(xs) - min(xs),
                        "height_mm": max(ys) - min(ys),
                        "area_mm2": (max(xs) - min(xs)) * (max(ys) - min(ys)),
                    }
                    return {
                        "filename": file_path.name,
                        "primitives": converted_prims,
                        "bounds": bounds,
                        "primitive_errors": 0,
                        "tools": gerber_tools,
                        "drill_count": len(converted_prims),
                        "source_info": {
                            "source": "gerber_fallback",
                            "units": gerber_res.get("units", "metric"),
                        },
                    }
        except Exception:
            pass

        return {
            "filename": file_path.name,
            "primitives": [],
            "bounds": None,
            "error": "No drill hits parsed",
            "tools": tools,
            "drill_count": 0,
            "source_info": info,
        }

    xs, ys = [], []
    for p in primitives:
        x, y = p["center"]
        r = p["diameter"] / 2.0
        xs.extend((x-r, x+r)); ys.extend((y-r, y+r))
    bounds = {
        "x_min": min(xs), "x_max": max(xs), "y_min": min(ys), "y_max": max(ys),
        "width_mm": max(xs)-min(xs), "height_mm": max(ys)-min(ys),
        "area_mm2": (max(xs)-min(xs))*(max(ys)-min(ys)),
    }
    return {
        "filename": file_path.name,
        "primitives": primitives,
        "bounds": bounds,
        "primitive_errors": parse_errors,
        "tools": tools,
        "drill_count": len(primitives),
        "source_info": info,
    }


# ============================================================
# DRILL REFERENCE TARGETS
# ============================================================

def _cluster_centers(items, tol=0.01):
    """Fast spatial-hash clustering; avoids O(N²) on large Gerbers."""
    if not items:
        return []
    cell=max(float(tol), 1e-6)
    grid={}
    clusters=[]
    for item in items:
        x,y=item["center"]
        gx,gy=int(math.floor(x/cell)),int(math.floor(y/cell))
        found=None
        # Check neighboring cells so points near a cell boundary still merge.
        for ix in (gx-1,gx,gx+1):
            for iy in (gy-1,gy,gy+1):
                for ci in grid.get((ix,iy),[]):
                    c=clusters[ci]
                    if math.hypot(x-c["x"],y-c["y"])<=tol:
                        found=c; break
                if found: break
            if found: break
        if found is None:
            ci=len(clusters)
            clusters.append({"x":x,"y":y,"diameters":[item["diameter"]],"layers":{item["layer"]},"count":1})
            grid.setdefault((gx,gy),[]).append(ci)
        else:
            n=found["count"]
            found["x"]=(found["x"]*n+x)/(n+1)
            found["y"]=(found["y"]*n+y)/(n+1)
            found["diameters"].append(item["diameter"])
            found["layers"].add(item["layer"])
            found["count"]+=1
    return clusters

def _collect_drill_reference_targets(layers):
    """Find likely plated-hole pad centers from actual Gerber geometry.

    Some Gerber writers omit hole_diameter from Circle primitives. In that
    case the copper pad itself is still an excellent coordinate reference.
    We therefore use repeated circular flashes from copper/mask layers rather
    than requiring a Gerber hole_diameter field.
    """
    candidates = []
    for layer in layers:
        if str(layer.get("category") or "").lower() == "drill":
            continue
        lname = str(layer.get("layer") or "").lower()
        if not ("copper" in lname or "solder mask" in lname):
            continue
        for p in (layer.get("geometry") or {}).get("primitives", []) or []:
            if p.get("type") != "circle":
                continue
            c = p.get("center")
            d = _num(p.get("diameter"), 0.0)
            if not (isinstance(c, (list, tuple)) and len(c) >= 2 and d > 0):
                continue
            candidates.append({"center": [float(c[0]), float(c[1])], "diameter": d, "layer": layer.get("layer", "")})

    clusters = _cluster_centers(candidates, tol=0.01)
    targets = []
    for c in clusters:
        # Repetition across layers is strong evidence of a plated through-hole.
        if len(c["layers"]) >= 2 or c["count"] >= 2:
            d = sorted(c["diameters"])[len(c["diameters"])//2]
            targets.append({
                "center": [c["x"], c["y"]],
                "diameter": d,
                "evidence_layers": sorted(c["layers"]),
                "occurrences": c["count"],
            })
    return targets


def _make_target_grid(targets, cell=0.25):
    grid={}
    for i,t in enumerate(targets):
        x,y=t["center"]; key=(int(math.floor(x/cell)),int(math.floor(y/cell)))
        grid.setdefault(key,[]).append(i)
    return grid,cell


def _nearest_target(x,y,targets,grid,cell,tolerance=0.18):
    gx,gy=int(math.floor(x/cell)),int(math.floor(y/cell))
    best=None
    reach=max(1,int(math.ceil(tolerance/cell)))
    for ix in range(gx-reach,gx+reach+1):
        for iy in range(gy-reach,gy+reach+1):
            for ti in grid.get((ix,iy),()):
                tc=targets[ti]["center"]
                d=math.hypot(x-tc[0],y-tc[1])
                if d<=tolerance and (best is None or d<best[0]):
                    best=(d,ti)
    return best


def _score_transform(primitives,targets,sx,sy,tx,ty,tolerance=0.18,limit=None,grid=None,cell=None):
    if grid is None or cell is None:
        grid,cell=_make_target_grid(targets)
    pairs=[]
    iterable=primitives if limit is None else primitives[:limit]
    for di,drill in enumerate(iterable):
        dc=drill.get("center")
        if not dc: continue
        hit=_nearest_target(sx*dc[0]+tx,sy*dc[1]+ty,targets,grid,cell,tolerance)
        if hit: pairs.append((hit[0],di,hit[1]))
    pairs.sort()
    used_d=set(); used_t=set(); matches=[]
    for dist,di,ti in pairs:
        if di in used_d or ti in used_t: continue
        used_d.add(di); used_t.add(ti); matches.append((dist,di,ti))
    return matches


def _representative_points(points, limit):
    """Return a small deterministic sample from point/dict records.

    The V9 records are dictionaries containing ``center``; older callers may
    pass plain ``[x, y]`` points.  Normalize only for selection so the
    original records are returned unchanged.
    """
    if not points:
        return []

    def xy(p):
        if isinstance(p, dict):
            c = p.get("center")
        else:
            c = p
        if isinstance(c, (list, tuple)) and len(c) >= 2:
            try:
                return float(c[0]), float(c[1])
            except (TypeError, ValueError):
                pass
        return None

    valid = [p for p in points if xy(p) is not None]
    if len(valid) <= limit:
        return valid

    picks = []
    for key_index, sign in ((0, 1), (1, 1), (0, -1), (1, -1)):
        picks.append(min(valid, key=lambda p: sign * xy(p)[key_index]))

    remaining = max(1, limit - len(picks))
    step = max(1, len(valid) // remaining)
    picks.extend(valid[i] for i in range(0, len(valid), step))

    out = []
    seen = set()
    for p in picks:
        x, y = xy(p)
        k = (round(x, 9), round(y, 9))
        if k not in seen:
            seen.add(k)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def _drills_already_in_board_coordinates(geometry, board_bounds, margin_mm=1.5):
    """Return True when converted Excellon coordinates already fit the Gerber board."""
    if not geometry or not geometry.get("primitives") or not board_bounds:
        return False

    xmin = float(board_bounds["x_min"]) - margin_mm
    xmax = float(board_bounds["x_max"]) + margin_mm
    ymin = float(board_bounds["y_min"]) - margin_mm
    ymax = float(board_bounds["y_max"]) + margin_mm

    pts = [
        p.get("center")
        for p in geometry.get("primitives", [])
        if isinstance(p.get("center"), (list, tuple)) and len(p["center"]) >= 2
    ]
    if not pts:
        return False

    in_bounds = sum(
        1 for c in pts
        if xmin <= float(c[0]) <= xmax and ymin <= float(c[1]) <= ymax
    )
    # Require majority (85%+) of drill points within board bounds to avoid outlier/park hits triggering full registration.
    return (in_bounds / len(pts)) >= 0.85


def _register_excellon_geometry(geometry, board_bounds, reference_targets):
    """Fast, bounded drill-to-Gerber registration.

    Applies alignment translation (tx, ty) or standard unit scaling (25.4)
    without warping relative drill hit spacing or applying local individual drill distortion.
    """
    if not geometry or not geometry.get("primitives"):
        return geometry
    primitives = geometry["primitives"]
    if not reference_targets:
        geometry["registration"] = {"applied": False, "method": "no_gerber_pad_references", "matched_holes": 0, "target_count": 0}
        return geometry

    drill_pts = _representative_points(primitives, 12)
    target_pts = _representative_points(reference_targets, 32)

    # Restrict scales to standard physical unit ratios and reasonable integer factors (no extreme candidate scales or reflections)
    scales = (1.0, 25.4, 1.0 / 25.4, 0.1, 10.0)
    candidates = {(s, s) for s in scales}

    target_grid, target_cell = _make_target_grid(reference_targets)
    best = None

    for sx, sy in candidates:
        if not (math.isfinite(sx) and math.isfinite(sy)) or sx == 0 or sy == 0:
            continue
        for d in drill_pts:
            dc = d.get("center")
            if not dc:
                continue
            for t in target_pts:
                tc = t["center"]
                tx, ty = tc[0] - sx * dc[0], tc[1] - sy * dc[1]
                pairs = _score_transform(primitives, reference_targets, sx, sy, tx, ty, limit=min(96, len(primitives)), grid=target_grid, cell=target_cell)
                if len(pairs) < 2:
                    continue
                err = sum(p[0] for p in pairs)
                key = (len(pairs), -err, -abs(math.log10(abs(sx))), -abs(math.log10(abs(sy))))
                if best is None or key > best["key"]:
                    best = {"key": key, "sx": sx, "sy": sy, "tx": tx, "ty": ty, "pairs": pairs}

    if best is None:
        geometry["registration"] = {"applied": False, "method": "no_reliable_match", "matched_holes": 0, "target_count": len(reference_targets)}
        return geometry

    full_pairs = _score_transform(primitives, reference_targets, best["sx"], best["sy"], best["tx"], best["ty"], limit=None, grid=target_grid, cell=target_cell)
    if len(full_pairs) >= len(best["pairs"]):
        best["pairs"] = full_pairs

    # Apply global transformation to all primitives uniformly (preserving geometry structure)
    for p in primitives:
        c = p.get("center")
        if c:
            c[0] = best["sx"] * c[0] + best["tx"]
            c[1] = best["sy"] * c[1] + best["ty"]

    xs, ys = [], []
    for p in primitives:
        x, y = p["center"]
        r = abs(_num(p.get("diameter"), 0)) / 2.0
        xs.extend((x - r, x + r))
        ys.extend((y - r, y + r))
    if xs and ys:
        geometry["bounds"] = {
            "x_min": min(xs), "x_max": max(xs),
            "y_min": min(ys), "y_max": max(ys),
            "width_mm": max(xs) - min(xs),
            "height_mm": max(ys) - min(ys),
            "area_mm2": (max(xs) - min(xs)) * (max(ys) - min(ys))
        }
    geometry["registration"] = {
        "applied": True,
        "method": "gerber_pad_alignment_fast",
        "x_scale": best["sx"],
        "y_scale": best["sy"],
        "x_offset_mm": best["tx"],
        "y_offset_mm": best["ty"],
        "matched_holes": len(best["pairs"]),
        "target_count": len(reference_targets),
        "total_match_error_mm": sum(x[0] for x in best["pairs"])
    }
    return geometry

# ============================================================
# BUILD VIEWER DATA
# ============================================================

def build_viewer_data(extracted_path, project_files, board_analysis=None):
    extracted_path=Path(extracted_path)
    layers=[]; errors=[]
    for item in project_files:
        filename=item.get("filename")
        if not filename: continue
        file_path=Path(item.get("path") or (extracted_path/filename))
        if not file_path.exists(): file_path=extracted_path/filename
        if not file_path.exists():
            errors.append({"filename":filename,"error":"File not found"}); continue
        file_type=str(item.get("file_type") or "Unknown").lower()
        is_drill=(file_type=="excellon") or str(item.get("category") or "").lower()=="drill"
        if is_drill:
            raw=str(item.get("layer") or "Drill")
            layer=raw if raw.lower() in {"drill","pth drill","npth drill","blind via drill","buried via drill","microvia / laser drill","via drill","routed / slot drill"} else ("NPTH Drill" if "npth" in filename.lower() else "PTH Drill" if "pth" in filename.lower() else "Drill")
            geometry=read_excellon_geometry(file_path)
        elif file_type=="gerber" or str(item.get("category") or "").lower()=="gerber":
            layer=_normalize_layer(item,file_path)
            geometry=read_gerber_geometry(file_path)
        else:
            continue
        if geometry.get("error") and not geometry.get("primitives"):
            errors.append({"filename":filename,"error":geometry.get("error")})
        layers.append({"layer":layer,"name":layer,"filename":filename,"category":"drill" if is_drill else "gerber","geometry":geometry,"confidence":item.get("confidence"),"classification_source":item.get("classification_source")})
    layers.sort(key=_layer_sort)

    board_bounds=None
    if isinstance(board_analysis, dict):
        dims = board_analysis.get("dimensions")
        if isinstance(dims, dict):
            try:
                x_min = float(dims["x_min"]) if dims.get("x_min") is not None else None
                x_max = float(dims["x_max"]) if dims.get("x_max") is not None else None
                y_min = float(dims["y_min"]) if dims.get("y_min") is not None else None
                y_max = float(dims["y_max"]) if dims.get("y_max") is not None else None
                if (
                    x_min is not None and x_max is not None and
                    y_min is not None and y_max is not None and
                    x_max > x_min and y_max > y_min
                ):
                    board_bounds = {
                        "x_min": x_min,
                        "x_max": x_max,
                        "y_min": y_min,
                        "y_max": y_max,
                        "width_mm": float(dims.get("width_mm", x_max - x_min)),
                        "height_mm": float(dims.get("height_mm", y_max - y_min)),
                        "area_mm2": float(dims.get("area_mm2", (x_max - x_min) * (y_max - y_min))),
                    }
            except (ValueError, TypeError):
                board_bounds = None

    if not board_bounds:
        outline_bounds=None
        for layer in layers:
            if layer["layer"] in {"Board Outline","Board Profile"} and layer["geometry"].get("bounds"):
                outline_bounds=layer["geometry"]["bounds"]; break
        non=[l["geometry"].get("bounds") for l in layers if l["category"]!="drill" and l["geometry"].get("bounds")]
        if outline_bounds: board_bounds=dict(outline_bounds)
        elif non:
            board_bounds={"x_min":min(b["x_min"] for b in non),"x_max":max(b["x_max"] for b in non),"y_min":min(b["y_min"] for b in non),"y_max":max(b["y_max"] for b in non)}
            board_bounds.update(width_mm=board_bounds["x_max"]-board_bounds["x_min"],height_mm=board_bounds["y_max"]-board_bounds["y_min"],area_mm2=(board_bounds["x_max"]-board_bounds["x_min"])*(board_bounds["y_max"]-board_bounds["y_min"]))
        else: board_bounds=None

    targets=_collect_drill_reference_targets(layers)
    for layer in layers:
        if layer["category"]!="drill":
            continue

        geometry=layer.get("geometry")

        if _drills_already_in_board_coordinates(
            geometry,
            board_bounds,
            margin_mm=0.5
        ):
            geometry["registration"]={
                "applied":False,
                "method":"native_gerber_coordinate_system",
                "matched_holes":0,
                "target_count":len(targets),
                "x_scale":1.0,
                "y_scale":1.0,
                "x_offset_mm":0.0,
                "y_offset_mm":0.0,
            }
            layer["geometry"]=geometry
        else:
            layer["geometry"]=_register_excellon_geometry(
                geometry,
                board_bounds,
                targets
            )
    layers.sort(key=_layer_sort)
    total_drills = sum(len(l.get("geometry", {}).get("primitives", [])) for l in layers if l.get("category") == "drill")

    outline_geometry = None
    for layer in layers:
        if layer.get("layer") in {"Board Outline", "Board Profile"} and layer.get("geometry"):
            outline_geometry = layer.get("geometry")
            break
    if not outline_geometry:
        for layer in layers:
            l_str = str(layer.get("layer", "")).lower()
            if ("outline" in l_str or "profile" in l_str or "border" in l_str or "edge" in l_str) and layer.get("geometry"):
                outline_geometry = layer.get("geometry")
                break

    return {"units":"mm","geometry_version":"2026-09-15-vector-v11-macro-drill-fix","board_bounds":board_bounds,"board_analysis":board_analysis,"total_drills":total_drills,"outline_geometry":outline_geometry,"drill_registration":{"reference_targets":len(targets),"reference_source":"repeated Gerber copper/solder-mask circular flashes"},"errors":errors,"layers":layers}

# ============================================================
# SIMPLE GEOMETRY STATS
# ============================================================

def geometry_stats(viewer_data):
    stats = {
        "layers": 0,
        "primitives": 0,
        "by_layer": {},
    }

    for layer in viewer_data.get("layers", []):
        name = layer.get("layer", "Unknown")
        count = len(
            layer.get(
                "geometry",
                {}
            ).get(
                "primitives",
                []
            )
        )

        stats["layers"] += 1
        stats["primitives"] += count
        stats["by_layer"][name] = count

    return stats
