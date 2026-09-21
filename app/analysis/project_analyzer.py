from pathlib import Path

from app.analysis.board_analyzer import analyze_board_from_gerber


GERBER_EXTENSIONS = {
    ".gbr",
    ".ger",
    ".pho",
    ".art",
    ".gtl",
    ".gbl",
    ".g1",
    ".g2",
    ".g3",
    ".g4",
    ".gko",
    ".gm1",
    ".gml",
    ".gto",
    ".gbo",
    ".gts",
    ".gbs",
    ".gdd",
    ".gdl",
}


OUTLINE_KEYWORDS = [
    "outline",
    "boardoutline",
    "board_outline",
    "profile",
    "edgecuts",
    "edge_cuts",
    "mechanical",
]


def is_gerber_file(file_path: Path):

    extension = file_path.suffix.lower()

    if extension in GERBER_EXTENSIONS:
        return True

    return False


def get_outline_priority(file_path: Path):

    name = file_path.name.lower()

    # Highest priority:
    # Explicit board outline / profile file
    for keyword in OUTLINE_KEYWORDS:
        if keyword in name:
            return 100

    # Common Gerber outline extensions
    if file_path.suffix.lower() in {
        ".gko",
        ".gm1",
        ".gml"
    }:
        return 90

    # Other layers can still contain the outline
    return 10


def analyze_project_board(extracted_path: Path):

    candidates = []

    for file_path in extracted_path.rglob("*"):

        if not file_path.is_file():
            continue

        if not is_gerber_file(file_path):
            continue

        try:

            result = analyze_board_from_gerber(
                file_path
            )

            if not result.get("outline_found"):
                continue

            dimensions = result.get("dimensions")

            if not dimensions:
                continue

            width = dimensions.get("width_mm", 0)
            height = dimensions.get("height_mm", 0)

            if width <= 0 or height <= 0:
                continue

            candidates.append({
                "file": file_path.name,
                "path": str(file_path),
                "priority": get_outline_priority(
                    file_path
                ),
                "analysis": result,
                "area": (
                    width * height
                )
            })

        except Exception as e:

            print(
                f"Board analysis error "
                f"for {file_path.name}: {e}"
            )

    if not candidates:

        return {
            "outline_found": False,
            "message": "No board outline detected."
        }

    # ------------------------------------------------
    # Sort candidates
    #
    # First by outline priority
    # Then by closed contour count
    # Then by board area
    # ------------------------------------------------

    candidates.sort(
        key=lambda item: (
            item["priority"],
            item["analysis"].get(
                "closed_contours",
                0
            ),
            item["area"]
        ),
        reverse=True
    )

    best = candidates[0]

    confidence = 50

    if best["priority"] >= 90:
        confidence += 35

    if best["analysis"].get(
        "closed_contours",
        0
    ) > 0:
        confidence += 10

    confidence = min(confidence, 99)

    return {
        "outline_found": True,

        "outline_file": best["file"],

        "source_layer": best["file"],

        "confidence": confidence,

        "method": (
            "explicit_outline_file"
            if best["priority"] >= 90
            else "geometry_detection"
        ),

        "dimensions": best["analysis"][
            "dimensions"
        ],

        "candidates_found": len(candidates),

        "candidates": [
            {
                "file": item["file"],
                "priority": item["priority"],
                "width_mm": item["analysis"][
                    "dimensions"
                ]["width_mm"],
                "height_mm": item["analysis"][
                    "dimensions"
                ]["height_mm"],
                "closed_contours": item["analysis"].get(
                    "closed_contours",
                    0
                )
            }
            for item in candidates
        ]
    }