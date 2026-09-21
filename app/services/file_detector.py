from pathlib import Path


def detect_file_type(filename: str):
    """
    Detect PCB file type based on filename and extension.
    This is the first detection layer.
    Later we will add content-based detection.
    """

    name = filename.lower()
    extension = Path(filename).suffix.lower()

    # -------------------------
    # DRILL FILES
    # -------------------------

    if extension in [".drl", ".xln", ".xlnc"]:
        if "npth" in name:
            return {
                "category": "drill",
                "layer": "NPTH Drill"
            }

        if "pth" in name:
            return {
                "category": "drill",
                "layer": "PTH Drill"
            }

        return {
            "category": "drill",
            "layer": "Drill"
        }

    # -------------------------
    # GERBER COPPER
    # -------------------------

    if extension == ".gtl" or "toplayer" in name:
        return {
            "category": "gerber",
            "layer": "Top Copper"
        }

    if extension == ".gbl" or "bottomlayer" in name:
        return {
            "category": "gerber",
            "layer": "Bottom Copper"
        }

    # -------------------------
    # SOLDER MASK
    # -------------------------

    if extension == ".gts" or "topsoldermask" in name:
        return {
            "category": "gerber",
            "layer": "Top Solder Mask"
        }

    if extension == ".gbs" or "bottomsoldermask" in name:
        return {
            "category": "gerber",
            "layer": "Bottom Solder Mask"
        }

    # -------------------------
    # SILKSCREEN
    # -------------------------

    if extension == ".gto" or "topsilkscreen" in name:
        return {
            "category": "gerber",
            "layer": "Top Silkscreen"
        }

    if extension == ".gbo" or "bottomsilkscreen" in name:
        return {
            "category": "gerber",
            "layer": "Bottom Silkscreen"
        }

    # -------------------------
    # BOARD OUTLINE
    # -------------------------

    if extension in [".gko", ".gm1", ".gml"]:
        return {
            "category": "gerber",
            "layer": "Board Outline"
        }

    if "boardoutline" in name or "outline" in name:
        return {
            "category": "gerber",
            "layer": "Board Outline"
        }

    # -------------------------
    # OTHER GERBER FILES
    # -------------------------

    if extension in [
        ".gbr",
        ".ger",
        ".art",
        ".pho",
        ".gdl",
        ".gdd"
    ]:
        return {
            "category": "gerber",
            "layer": "Other Gerber"
        }

    # -------------------------
    # UNKNOWN
    # -------------------------

    return {
        "category": "other",
        "layer": "Unknown"
    }


def analyze_files(files):
    """
    Analyze all extracted files.
    """

    detected_files = []

    for filename in files:

        detection = detect_file_type(filename)

        detected_files.append({
            "filename": filename,
            "category": detection["category"],
            "layer": detection["layer"]
        })

    return detected_files