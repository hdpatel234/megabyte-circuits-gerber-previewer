# ============================================================
# GERBER VECTOR VIEWER
# Accurate Gerber geometry -> browser JSON
# ============================================================

from pathlib import Path
import math
import gerber


# ============================================================
# BASIC HELPERS
# ============================================================

def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
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

    return {
        "type": "circle",
        "center": _point(position),
        "diameter": _num(
            _get(primitive, "diameter", 0.0),
            0.0
        ),
        "hole_diameter": _num(
            _get(primitive, "hole_diameter", 0.0),
            0.0
        ),
        "polarity": _polarity(primitive),
    }


# ============================================================
# RECTANGLE
# ============================================================

def _convert_rectangle(primitive):
    return {
        "type": "rectangle",
        "position": _point(
            _get(primitive, "position")
        ),
        "width": _num(
            _get(primitive, "width", 0.0),
            0.0
        ),
        "height": _num(
            _get(primitive, "height", 0.0),
            0.0
        ),
        "rotation": _num(
            _get(primitive, "rotation", 0.0),
            0.0
        ),
        "polarity": _polarity(primitive),
    }


# ============================================================
# OBRROUND
# ============================================================

def _convert_obround(primitive):
    return {
        "type": "obround",
        "position": _point(
            _get(primitive, "position")
        ),
        "width": _num(
            _get(primitive, "width", 0.0),
            0.0
        ),
        "height": _num(
            _get(primitive, "height", 0.0),
            0.0
        ),
        "rotation": _num(
            _get(primitive, "rotation", 0.0),
            0.0
        ),
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


def _convert_region(primitive):
    """
    Regions are filled Gerber geometry, not stroked centerlines.

    Convert each connected child sequence into one or more closed paths.
    Arcs are already flattened by _convert_primitive().
    """
    paths = []
    current = []

    for child in _get(primitive, "primitives", []) or []:
        converted = _convert_primitive(child)
        path = _primitive_path(converted)

        if not path or len(path) < 2:
            continue

        if not current:
            current = [path[0], path[1]]
            continue

        last = current[-1]
        first = path[0]

        if (
            math.isclose(last[0], first[0], abs_tol=1e-9)
            and math.isclose(last[1], first[1], abs_tol=1e-9)
        ):
            current.extend(path[1:])
        else:
            paths.append(current)
            current = [path[0], path[1]]

    if current:
        paths.append(current)

    normalized = []
    for path in paths:
        if len(path) < 3:
            continue

        if (
            not math.isclose(path[0][0], path[-1][0], abs_tol=1e-9)
            or not math.isclose(path[0][1], path[-1][1], abs_tol=1e-9)
        ):
            path = path + [path[0]]

        normalized.append(path)

    return {
        "type": "region",
        "paths": normalized,
        "polarity": _polarity(primitive),
    }


# ============================================================
# GENERIC PRIMITIVE
# ============================================================

def _convert_primitive(primitive):
    if primitive is None:
        return None

    name = _primitive_name(primitive)

    # Region must be checked before generic "line"/"arc" tests.
    if (
        "region" in name
        or (
            hasattr(primitive, "primitives")
            and not hasattr(primitive, "start")
        )
    ):
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

    if "circle" in name or (
        hasattr(primitive, "position")
        and hasattr(primitive, "diameter")
    ):
        return _convert_circle(primitive)

    if "rectangle" in name:
        return _convert_rectangle(primitive)

    if (
        "obround" in name
        or "oval" in name
        or "oblong" in name
    ):
        return _convert_obround(primitive)

    # pcb-tools can expose aperture-macro flashes as primitives with a
    # position but without a simple diameter. Preserve what is available.
    position = _get(primitive, "position")
    if position is not None:
        diameter = _num(
            _get(primitive, "diameter", 0.0),
            0.0
        )
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
            if converted:
                primitives.append(converted)
        except Exception:
            primitive_errors += 1

    return {
        "filename": file_path.name,
        "primitives": primitives,
        "bounds": _geometry_bounds(primitives),
        "primitive_errors": primitive_errors,
    }


# ============================================================
# LAYER ORDER
# ============================================================

_LAYER_ORDER = {
    "Board Outline": 0,
    "Bottom Copper": 10,
    "Top Copper": 20,
    "Bottom Solder Mask": 30,
    "Top Solder Mask": 40,
    "Bottom Silkscreen": 50,
    "Top Silkscreen": 60,
}


def _layer_sort(item):
    layer = item.get("layer", "")
    if layer in _LAYER_ORDER:
        return _LAYER_ORDER[layer]

    if str(layer).lower().startswith("inner copper"):
        return 15

    return 100


# ============================================================
# BUILD VIEWER DATA
# ============================================================

def build_viewer_data(
    extracted_path,
    project_files
):
    extracted_path = Path(extracted_path)

    layers = []

    for item in project_files:
        if item.get("category") != "gerber":
            continue

        layer = item.get("layer", "Unknown")
        filename = item.get("filename")

        if not filename:
            continue

        file_path = (
            extracted_path
            / filename
        )

        if not file_path.exists():
            # Preserve support for project_files containing absolute paths.
            candidate = Path(
                item.get("path", "")
            )
            if candidate.exists():
                file_path = candidate
            else:
                continue

        geometry = read_gerber_geometry(
            file_path
        )

        layers.append({
            "layer": layer,
            "name": layer,
            "filename": filename,
            "geometry": geometry,
        })

    layers.sort(
        key=_layer_sort
    )

    # Prefer the actual Board Outline geometry for global bounds.
    outline_bounds = None
    for layer in layers:
        if layer["layer"] == "Board Outline":
            outline_bounds = (
                layer["geometry"].get("bounds")
            )
            if outline_bounds:
                break

    all_bounds = []
    for layer in layers:
        bounds = layer["geometry"].get("bounds")
        if bounds:
            all_bounds.append(bounds)

    if outline_bounds:
        board_bounds = outline_bounds
    elif all_bounds:
        board_bounds = {
            "x_min": min(b["x_min"] for b in all_bounds),
            "x_max": max(b["x_max"] for b in all_bounds),
            "y_min": min(b["y_min"] for b in all_bounds),
            "y_max": max(b["y_max"] for b in all_bounds),
        }
        board_bounds["width_mm"] = (
            board_bounds["x_max"] - board_bounds["x_min"]
        )
        board_bounds["height_mm"] = (
            board_bounds["y_max"] - board_bounds["y_min"]
        )
        board_bounds["area_mm2"] = (
            board_bounds["width_mm"]
            * board_bounds["height_mm"]
        )
    else:
        board_bounds = None

    return {
        "units": "mm",
        "geometry_version": "2026-09-01-vector-v3",
        "board_bounds": board_bounds,
        "layers": layers,
    }


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
