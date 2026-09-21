from pathlib import Path
from app.parsers.excellon_parser import parse_excellon


def analyze_drill_files(extracted_dir: Path, detected_files):
    """
    Analyze all detected drill files.
    """

    drill_results = []

    total_hits = 0
    all_diameters = []

    for item in detected_files:

        if item["category"] != "drill":
            continue

        file_path = extracted_dir / item["filename"]

        if not file_path.exists():
            continue

        result = parse_excellon(file_path)

        drill_results.append({
            "filename": item["filename"],
            "analysis": result
        })

        if "total_hits" in result:
            total_hits += result["total_hits"]

        if "tools" in result:
            for tool in result["tools"]:
                all_diameters.append(tool["diameter"])

    return {
        "drill_files": len(drill_results),
        "total_drill_hits": total_hits,
        "minimum_drill": (
            min(all_diameters)
            if all_diameters else None
        ),
        "maximum_drill": (
            max(all_diameters)
            if all_diameters else None
        ),
        "files": drill_results
    }