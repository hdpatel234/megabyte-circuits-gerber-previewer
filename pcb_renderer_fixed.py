from pathlib import Path
from PIL import Image, ImageDraw
import math
import gerber


# ============================================================
# HELPERS
# ============================================================

def _safe_read(path):
    try:
        return gerber.read(str(path))
    except Exception as e:
        print(f"Gerber/Excellon read error: {path}: {e}")
        return None


def _primitive_bbox(primitive):
    try:
        bbox = primitive.bounding_box
        if bbox:
            return bbox
    except Exception:
        pass
    return None


def get_board_bounds(extracted_path, project_files):
    extracted_path = Path(extracted_path)
    outline_file = None

    for item in project_files:
        if item.get("layer") == "Board Outline":
            outline_file = extracted_path / item["filename"]
            break

    if not outline_file or not outline_file.exists():
        return None

    g = _safe_read(outline_file)
    if g is None:
        return None

    min_x = float("inf")
    min_y = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")

    for primitive in g.primitives:
        bbox = _primitive_bbox(primitive)
        if not bbox:
            continue

        try:
            x1, x2 = bbox[0]
            y1, y2 = bbox[1]
            min_x = min(min_x, float(x1))
            max_x = max(max_x, float(x2))
            min_y = min(min_y, float(y1))
            max_y = max(max_y, float(y2))
        except Exception:
            continue

    if min_x == float("inf"):
        return None

    return {
        "min_x": min_x,
        "max_x": max_x,
        "min_y": min_y,
        "max_y": max_y,
    }


def mm_to_pixel(x, y, bounds, scale, padding):
    px = int(round((x - bounds["min_x"]) * scale + padding))
    py = int(round((bounds["max_y"] - y) * scale + padding))
    return px, py


def _diameter_from_aperture(primitive):
    try:
        aperture = primitive.aperture
        diameter = getattr(aperture, "diameter", None)
        if diameter:
            return float(diameter)
    except Exception:
        pass
    return 0.0


# ============================================================
# DRAW GERBER LAYER
# ============================================================

def draw_layer(draw, file_path, bounds, scale, padding, fill):
    g = _safe_read(file_path)
    if g is None:
        return

    for primitive in g.primitives:
        try:
            primitive_type = type(primitive).__name__

            if primitive_type == "Line":
                start = primitive.start
                end = primitive.end

                x1, y1 = mm_to_pixel(
                    start[0], start[1], bounds, scale, padding
                )
                x2, y2 = mm_to_pixel(
                    end[0], end[1], bounds, scale, padding
                )

                diameter = _diameter_from_aperture(primitive)
                width = max(1, int(round(diameter * scale))) if diameter else 1

                draw.line(
                    [(x1, y1), (x2, y2)],
                    fill=fill,
                    width=width,
                )

            elif primitive_type == "Circle":
                position = getattr(primitive, "position", None)
                diameter = getattr(primitive, "diameter", None)

                if position is None or diameter is None:
                    continue

                px, py = mm_to_pixel(
                    position[0], position[1], bounds, scale, padding
                )
                radius = max(1, int(round(float(diameter) * scale / 2.0)))

                draw.ellipse(
                    [
                        (px - radius, py - radius),
                        (px + radius, py + radius),
                    ],
                    fill=fill,
                )

            elif primitive_type == "Rectangle":
                bbox = _primitive_bbox(primitive)
                if not bbox:
                    continue

                x1, x2 = bbox[0]
                y1, y2 = bbox[1]

                p1 = mm_to_pixel(x1, y1, bounds, scale, padding)
                p2 = mm_to_pixel(x2, y2, bounds, scale, padding)

                draw.rectangle([p1, p2], fill=fill)

            elif hasattr(primitive, "vertices"):
                vertices = getattr(primitive, "vertices", None)
                if vertices:
                    points = [
                        mm_to_pixel(
                            point[0], point[1], bounds, scale, padding
                        )
                        for point in vertices
                    ]
                    if len(points) >= 3:
                        draw.polygon(points, fill=fill)

        except Exception as e:
            print(f"Primitive render error in {file_path.name}: {e}")


# ============================================================
# DRAW DRILL HOLES
# ============================================================

def _draw_hole(draw, px, py, diameter_px, hole_fill, ring_fill=None):
    # Always make very small holes visible at preview resolution.
    radius = max(2.0, diameter_px / 2.0)

    if ring_fill is not None:
        outer = radius + 1.5
        draw.ellipse(
            [
                (px - outer, py - outer),
                (px + outer, py + outer),
            ],
            fill=ring_fill,
        )

    draw.ellipse(
        [
            (px - radius, py - radius),
            (px + radius, py + radius),
        ],
        fill=hole_fill,
    )


def draw_drill_layer(
    draw,
    file_path,
    bounds,
    scale,
    padding,
    hole_fill=(20, 20, 20),
    ring_fill=None,
):
    drill = _safe_read(file_path)
    if drill is None:
        return

    count = 0

    for hit in getattr(drill, "primitives", []):
        try:
            position = getattr(hit, "position", None)
            diameter = getattr(hit, "diameter", None)

            if position is None or diameter is None:
                continue

            px, py = mm_to_pixel(
                position[0], position[1], bounds, scale, padding
            )

            diameter_px = float(diameter) * scale
            _draw_hole(
                draw,
                px,
                py,
                diameter_px,
                hole_fill,
                ring_fill,
            )
            count += 1

        except Exception as e:
            print(f"Drill primitive error in {file_path.name}: {e}")

    print(f"Rendered {count} drill hits from {file_path.name}")


# ============================================================
# DRAW BOARD OUTLINE
# ============================================================

def draw_board_outline(draw, extracted_path, project_files, bounds, scale, padding,
                       outline_fill=None, outline_width=2):
    for item in project_files:
        if item.get("layer") != "Board Outline":
            continue

        path = Path(extracted_path) / item["filename"]
        g = _safe_read(path)
        if g is None:
            return

        for primitive in g.primitives:
            try:
                if type(primitive).__name__ == "Line":
                    p1 = mm_to_pixel(
                        primitive.start[0],
                        primitive.start[1],
                        bounds,
                        scale,
                        padding,
                    )
                    p2 = mm_to_pixel(
                        primitive.end[0],
                        primitive.end[1],
                        bounds,
                        scale,
                        padding,
                    )
                    draw.line(
                        [p1, p2],
                        fill=outline_fill or (20, 20, 20),
                        width=outline_width,
                    )
                elif hasattr(primitive, "vertices"):
                    vertices = getattr(primitive, "vertices", None)
                    if vertices and len(vertices) >= 2:
                        points = [
                            mm_to_pixel(
                                p[0], p[1], bounds, scale, padding
                            )
                            for p in vertices
                        ]
                        draw.line(
                            points + [points[0]],
                            fill=outline_fill or (20, 20, 20),
                            width=outline_width,
                        )
            except Exception:
                continue
        return


# ============================================================
# LAYER ITERATOR
# ============================================================

def _items(project_files, layer):
    for item in project_files:
        if item.get("layer") == layer:
            yield item


def _draw_named_layers(
    draw,
    extracted_path,
    project_files,
    layers,
    bounds,
    scale,
    padding,
    colors,
):
    for layer in layers:
        for item in _items(project_files, layer):
            path = Path(extracted_path) / item["filename"]
            if path.exists():
                draw_layer(
                    draw,
                    path,
                    bounds,
                    scale,
                    padding,
                    colors.get(layer, (100, 100, 100)),
                )


def _draw_all_drills(
    draw,
    extracted_path,
    project_files,
    bounds,
    scale,
    padding,
    hole_fill,
    ring_fill=None,
):
    for item in project_files:
        if item.get("category") != "drill":
            continue

        path = Path(extracted_path) / item["filename"]
        if path.exists():
            draw_drill_layer(
                draw,
                path,
                bounds,
                scale,
                padding,
                hole_fill=hole_fill,
                ring_fill=ring_fill,
            )


# ============================================================
# 3D STYLE TRANSFORMATION
# ============================================================

def _iso_point(x, y, ox, oy, sx, sy, skew_x, skew_y):
    return (
        int(round(ox + x * sx + y * skew_x)),
        int(round(oy + y * sy + x * skew_y)),
    )


def _make_3d_preview(
    image2d,
    image_width,
    image_height,
    thickness_px=12,
):
    # This is a visual 3D-style preview, not a CAD solid model.
    # The actual copper/drill geometry is retained from the 2D render.
    canvas = Image.new(
        "RGB",
        (image_width + 80, image_height + 80),
        (30, 30, 30),
    )

    # Create a perspective-like top surface.
    top = image2d.convert("RGBA")
    top = top.resize(
        (image_width, image_height),
        Image.Resampling.LANCZOS,
    )

    # Shadow/extrusion layers.
    for i in range(thickness_px, 0, -1):
        layer = Image.new(
            "RGBA",
            canvas.size,
            (0, 0, 0, 0),
        )
        layer.alpha_composite(
            top,
            (35 + i, 25 + i),
        )
        canvas.paste(layer, (0, 0), layer)

    # Top board image.
    canvas.paste(top, (35, 25), top)

    draw = ImageDraw.Draw(canvas)

    # Visible lower/right extrusion edges.
    draw.line(
        [
            (35, 25 + image_height),
            (35 + thickness_px, 25 + image_height + thickness_px),
            (35 + image_width + thickness_px, 25 + image_height + thickness_px),
        ],
        fill=(10, 50, 28),
        width=3,
    )

    draw.line(
        [
            (35 + image_width, 25),
            (35 + image_width + thickness_px, 25 + thickness_px),
            (
                35 + image_width + thickness_px,
                25 + image_height + thickness_px,
            ),
        ],
        fill=(10, 50, 28),
        width=3,
    )

    return canvas


# ============================================================
# GENERATE PCB PREVIEWS
# ============================================================

def generate_pcb_previews(project_path, extracted_path, project_files):
    project_path = Path(project_path)
    extracted_path = Path(extracted_path)

    render_dir = project_path / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)

    bounds = get_board_bounds(extracted_path, project_files)

    if not bounds:
        return {
            "success": False,
            "error": "Board outline not found.",
        }

    width_mm = bounds["max_x"] - bounds["min_x"]
    height_mm = bounds["max_y"] - bounds["min_y"]

    # High enough resolution to show 0.305 mm drills clearly.
    scale = 12
    padding = 50

    image_width = max(
        400,
        int(round(width_mm * scale + padding * 2)),
    )
    image_height = max(
        300,
        int(round(height_mm * scale + padding * 2)),
    )

    # ========================================================
    # 2D PREVIEW
    # ========================================================

    image2d = Image.new(
        "RGB",
        (image_width, image_height),
        (242, 242, 242),
    )
    draw2d = ImageDraw.Draw(image2d)

    # Board base.
    board_p1 = mm_to_pixel(
        bounds["min_x"],
        bounds["max_y"],
        bounds,
        scale,
        padding,
    )
    board_p2 = mm_to_pixel(
        bounds["max_x"],
        bounds["min_y"],
        bounds,
        scale,
        padding,
    )

    draw2d.rectangle(
        [board_p1, board_p2],
        fill=(18, 92, 55),
    )

    # Top solder mask.
    _draw_named_layers(
        draw2d,
        extracted_path,
        project_files,
        ["Top Solder Mask"],
        bounds,
        scale,
        padding,
        {"Top Solder Mask": (20, 105, 65)},
    )

    # Bottom copper is shown first.
    _draw_named_layers(
        draw2d,
        extracted_path,
        project_files,
        ["Bottom Copper"],
        bounds,
        scale,
        padding,
        {"Bottom Copper": (155, 90, 45)},
    )

    # Top copper.
    _draw_named_layers(
        draw2d,
        extracted_path,
        project_files,
        ["Top Copper"],
        bounds,
        scale,
        padding,
        {"Top Copper": (218, 166, 45)},
    )

    # Silkscreen.
    _draw_named_layers(
        draw2d,
        extracted_path,
        project_files,
        ["Top Silkscreen"],
        bounds,
        scale,
        padding,
        {"Top Silkscreen": (238, 238, 238)},
    )

    _draw_named_layers(
        draw2d,
        extracted_path,
        project_files,
        ["Bottom Silkscreen"],
        bounds,
        scale,
        padding,
        {"Bottom Silkscreen": (190, 190, 190)},
    )

    # Drill holes MUST be last so they remain visible.
    _draw_all_drills(
        draw2d,
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        hole_fill=(22, 22, 22),
        ring_fill=(210, 210, 210),
    )

    # Board outline.
    draw_board_outline(
        draw2d,
        extracted_path,
        project_files,
        bounds,
        scale,
        padding,
        outline_fill=(8, 8, 8),
        outline_width=2,
    )

    preview_2d = render_dir / "pcb_2d_preview.png"
    image2d.save(preview_2d)

    # ========================================================
    # 3D-STYLE PREVIEW
    # ========================================================

    # Build a clean top surface from the same accurate geometry.
    image3d_surface = image2d.copy()

    # Give the board area a stronger visual frame.
    d3 = ImageDraw.Draw(image3d_surface)
    d3.rectangle(
        [board_p1, board_p2],
        outline=(5, 45, 25),
        width=3,
    )

    image3d = _make_3d_preview(
        image3d_surface,
        image_width,
        image_height,
        thickness_px=14,
    )

    preview_3d = render_dir / "pcb_3d_preview.png"
    image3d.save(preview_3d)

    return {
        "success": True,
        "board_size_mm": {
            "width": round(width_mm, 4),
            "height": round(height_mm, 4),
        },
        "renders": [
            {
                "name": "2D PCB Preview",
                "path": str(preview_2d),
            },
            {
                "name": "3D PCB Preview",
                "path": str(preview_3d),
            },
        ],
    }
