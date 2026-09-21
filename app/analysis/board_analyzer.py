from pathlib import Path

from app.parsers.gerber_parser import parse_gerber


def contour_area_score(contour):

    dimensions = contour.dimensions()

    if not dimensions:
        return 0

    return (
        dimensions["width_mm"]
        *
        dimensions["height_mm"]
    )


def analyze_board_from_gerber(file_path: Path):

    result = parse_gerber(file_path)

    contours = result["contours"]

    if not contours:
        return {
            "outline_found": False
        }

    closed_contours = []

    for contour in contours:

        if contour.is_closed():
            closed_contours.append(contour)

    # Prefer closed contours
    candidates = (
        closed_contours
        if closed_contours
        else contours
    )

    # Largest contour is normally the board outline
    board_contour = max(
        candidates,
        key=contour_area_score
    )

    dimensions = board_contour.dimensions()

    return {
        "outline_found": True,

        "contours_found": len(contours),

        "closed_contours": len(closed_contours),

        "dimensions": {
            "units": "mm",

            "x_min": round(
                dimensions["x_min"], 5
            ),

            "x_max": round(
                dimensions["x_max"], 5
            ),

            "y_min": round(
                dimensions["y_min"], 5
            ),

            "y_max": round(
                dimensions["y_max"], 5
            ),

            "width_mm": round(
                dimensions["width_mm"], 5
            ),

            "height_mm": round(
                dimensions["height_mm"], 5
            ),

            "area_mm2": round(
                dimensions["width_mm"]
                *
                dimensions["height_mm"],
                4
            )
        }
    }