from pathlib import Path

from app.parsers.gerber_outline_parser import (
    parse_gerber_bounds
)


def analyze_board(
    extracted_dir: Path,
    detected_files
):
    """
    Find the detected Board Outline file
    and calculate PCB dimensions.
    """

    outline_files = [

        item for item in detected_files

        if item["layer"] == "Board Outline"
    ]

    if not outline_files:

        return {
            "outline_found": False,
            "message":
                "Board outline file not found."
        }

    outline_file = outline_files[0]

    file_path = (
        extracted_dir /
        outline_file["filename"]
    )

    result = parse_gerber_bounds(
        file_path
    )

    return {

        "outline_found": True,

        "outline_file":
            outline_file["filename"],

        "dimensions":
            result
    }