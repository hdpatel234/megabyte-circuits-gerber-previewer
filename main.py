from gerber_viewer import build_viewer_data
from pcb_global_layer_classifier import classify_file
from nc_drill_parser import parse_headerless_nc_drill
import os
import re
import io
import uuid
import json
import shutil
import zipfile
import tarfile
import math
import gerber
import gerber_patch

from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from fastapi.responses import FileResponse

# PCB preview renderer is optional at import time so the DFM API can
# still start if a renderer dependency is temporarily unavailable.
try:
    from pcb_renderer import generate_pcb_previews
    PCB_RENDERER_IMPORT_ERROR = None
except Exception as e:
    generate_pcb_previews = None
    PCB_RENDERER_IMPORT_ERROR = str(e)

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from PIL import Image, ImageDraw


# ============================================================
# APP CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

PROJECT_DIR = BASE_DIR / "projects"
PROJECT_DIR.mkdir(parents=True, exist_ok=True)


app = FastAPI(
    title="PCB Gerber DFM Analyzer",
    version="1.0.0"
)

@app.get("/")
@app.get("/health")
@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "PCB Gerber DFM Analyzer",
        "version": "1.0.0",
        "instance": os.getenv("RENDER_INSTANCE_ID", os.getenv("HOSTNAME", "localhost")),
        "uptime_status": "ok",
        "renderer_available": generate_pcb_previews is not None,
    }


@app.get("/gerber_viewer.html")
def gerber_viewer_page():
    viewer_file = Path(__file__).resolve().parent / "gerber_viewer.html"

    if not viewer_file.exists():
        return {
            "success": False,
            "error": f"gerber_viewer.html not found: {viewer_file}"
        }

    return FileResponse(
        str(viewer_file),
        media_type="text/html"
    )


app.add_middleware(
    GZipMiddleware,
    minimum_size=2048,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount(
    "/projects",
    StaticFiles(directory=str(PROJECT_DIR)),
    name="projects"
)


# ============================================================
# FILE EXTENSIONS
# ============================================================

GERBER_EXTENSIONS = {
    ".gbr",
    ".ger",
    ".gtl",
    ".gbl",
    ".gts",
    ".gbs",
    ".gto",
    ".gbo",
    ".gko",
    ".gm1",
    ".gm2",
    ".gml",
    ".g1",
    ".g2",
    ".pho",
    ".art",
    ".sol",
    ".cmp",
    ".stc",
    ".sts",
    ".plc",
    ".pls",
    ".top",
    ".bot",
    ".outline",
    ".edge"
}


DRILL_EXTENSIONS = {
    ".drl",
    ".xln",
    ".txt",
    ".exc",
    ".tap"
}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def safe_filename(filename: str) -> str:
    return Path(filename).name


def read_text_file(file_path: Path) -> str:
    """
    Read Gerber / drill files safely.
    """

    try:
        ext = file_path.suffix.lower()
        if ext in {
            ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
            ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff",
            ".exe", ".dll", ".so", ".dylib", ".bin", ".xlsx", ".xls", ".docx", ".doc"
        }:
            return ""

        with open(file_path, "rb") as f:
            chunk = f.read(1024)
            if b"\x00" in chunk:
                return ""

        return file_path.read_text(
            encoding="utf-8",
            errors="ignore"
        )
    except Exception:
        return ""


def is_probably_gerber(file_path: Path) -> bool:
    """
    Detect Gerber file by content if extension is unknown.
    """

    text = read_text_file(file_path)

    if not text:
        return False

    checks = [
        "%FSL",
        "%MOMM",
        "%MOIN",
        "G04",
        "D01",
        "D02",
        "D03",
        "M02"
    ]

    score = sum(
        1 for item in checks
        if item in text
    )

    return score >= 3


def is_probably_drill(file_path: Path) -> bool:
    """
    Detect Excellon drill file.
    """

    text = read_text_file(file_path)

    if not text:
        return False

    checks = [
        "M48",
        "M95",
        "T01",
        "T02",
        "%"
    ]

    score = sum(
        1 for item in checks
        if item in text
    )

    return "M48" in text or score >= 3


# ============================================================
# ARCHIVE EXTRACTION
# ============================================================

def extract_archive(
    archive_path: Path,
    destination: Path
):
    """
    Extract ZIP archive.
    RAR is intentionally not included here because Python
    requires additional system support / package.
    """

    extension = archive_path.suffix.lower()

    if extension == ".zip":

        with zipfile.ZipFile(
            archive_path,
            "r"
        ) as zip_ref:

            for member in zip_ref.namelist():

                target_path = (
                    destination /
                    Path(member).name
                )

                if member.endswith("/"):
                    continue

                with zip_ref.open(member) as source:

                    with open(
                        target_path,
                        "wb"
                    ) as target:

                        shutil.copyfileobj(
                            source,
                            target
                        )

        return

    if extension == ".rar":
        try:
            rarfile = __import__("rarfile")
            with rarfile.RarFile(archive_path, "r") as rf:
                for member in rf.namelist():
                    if not member.endswith("/"):
                        target_path = destination / Path(member).name
                        with rf.open(member) as source, open(target_path, "wb") as target:
                            shutil.copyfileobj(source, target)
                return
        except Exception:
            pass

        executables = [
            r"C:\Program Files\7-Zip\7z.exe",
            r"C:\Program Files (x86)\7-Zip\7z.exe",
            r"C:\Program Files\WinRAR\UnRAR.exe",
            r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
            r"C:\Program Files\WinRAR\WinRAR.exe",
            "7z",
            "unrar"
        ]

        for exe in executables:
            if shutil.which(exe) or Path(exe).exists():
                try:
                    if "7z" in str(exe).lower():
                        cmd = [exe, "e", "-y", f"-o{destination}", str(archive_path)]
                    else:
                        cmd = [exe, "e", "-y", str(archive_path), f"-o+{destination}"]
                    res = subprocess.run(cmd, capture_output=True, text=True)
                    if res.returncode == 0:
                        return
                except Exception:
                    pass

    if extension in {".tar", ".gz", ".tgz"}:

        with tarfile.open(
            archive_path,
            "r:*"
        ) as tar_ref:

            for member in tar_ref.getmembers():

                if not member.isfile():
                    continue

                member.name = Path(
                    member.name
                ).name

                tar_ref.extract(
                    member,
                    destination
                )

        return

    raise Exception(
        f"Unsupported archive format: {extension}"
    )


# ============================================================
# GET ALL PROJECT FILES
# ============================================================

def get_project_files(
        extracted_path: Path
    ) -> List[Dict[str, Any]]:

        results = []

        for file_path in extracted_path.rglob("*"):

            if not file_path.is_file():
                continue

            # Read content so the global classifier can detect:
            # - Gerber X2 FileFunction
            # - Gerber syntax
            # - Excellon syntax
            # - filename conventions
            text = read_text_file(file_path)

            classification = classify_file(
                file_path.name,
                text=text
            )

            file_type = classification.get(
                "file_type",
                "Unknown"
            )

            layer = classification.get(
                "layer",
                "Unknown"
            )

            confidence = classification.get(
                "confidence",
                0
            )

            source = classification.get(
                "source",
                ""
            )

            # Normalize application categories.
            cat_layer = str(layer).lower()
            if layer in {"PTH Drill", "NPTH Drill", "Via Drill", "Blind Via Drill", "Buried Via Drill", "Drill"} or ("drill" in cat_layer and "drawing" not in cat_layer and "map" not in cat_layer):
                category = "drill"
            elif file_type == "Gerber":
                category = "gerber"
            elif file_type == "Excellon":
                category = "drill"
            else:
                category = "other"

            results.append({
                "filename": file_path.name,
                "category": category,
                "layer": layer,
                "confidence": confidence,
                "classification_source": source,
                "file_type": file_type,
                "extension": file_path.suffix.lower(),
                "path": str(file_path)
            })

        return results


# ============================================================
# LAYER CLASSIFICATION
# ============================================================

def classify_gerber_layer(
    filename: str
) -> str:

    name = filename.lower()
    ext = Path(filename).suffix.lower()

    # --------------------------------------------------------
    # BOARD OUTLINE
    # --------------------------------------------------------

    if (
        ext in {
            ".gko",
            ".gm1",
            ".gm2",
            ".gml",
            ".outline",
            ".edge"
        }
        or "outline" in name
        or "boardoutline" in name
        or "edge.cuts" in name
        or "edge_cut" in name
    ):

        return "Board Outline"

    # --------------------------------------------------------
    # TOP COPPER
    # --------------------------------------------------------

    if (
        ext == ".gtl"
        or "toplayer" in name
        or "top_copper" in name
        or "topcopper" in name
        or "f.cu" in name
    ):

        return "Top Copper"

    # --------------------------------------------------------
    # BOTTOM COPPER
    # --------------------------------------------------------

    if (
        ext == ".gbl"
        or "bottomlayer" in name
        or "bottom_copper" in name
        or "bottomcopper" in name
        or "b.cu" in name
    ):

        return "Bottom Copper"

    # --------------------------------------------------------
    # TOP MASK
    # --------------------------------------------------------

    if (
        ext == ".gts"
        or "topsoldermask" in name
        or "top_mask" in name
        or "f.mask" in name
    ):

        return "Top Solder Mask"

    # --------------------------------------------------------
    # BOTTOM MASK
    # --------------------------------------------------------

    if (
        ext == ".gbs"
        or "bottomsoldermask" in name
        or "bottom_mask" in name
        or "b.mask" in name
    ):

        return "Bottom Solder Mask"

    # --------------------------------------------------------
    # TOP SILK
    # --------------------------------------------------------

    if (
        ext == ".gto"
        or "topsilkscreen" in name
        or "top_silk" in name
        or "f.silks" in name
    ):

        return "Top Silkscreen"

    # --------------------------------------------------------
    # BOTTOM SILK
    # --------------------------------------------------------

    if (
        ext == ".gbo"
        or "bottomsilkscreen" in name
        or "bottom_silk" in name
        or "b.silks" in name
    ):

        return "Bottom Silkscreen"

    # --------------------------------------------------------
    # INNER COPPER
    # --------------------------------------------------------

    inner_patterns = [
        r"inner.*?(\d+)",
        r"layer.*?(\d+)",
        r"l(\d+)"
    ]

    for pattern in inner_patterns:

        match = re.search(
            pattern,
            name
        )

        if match:

            layer_number = int(
                match.group(1)
            )

            if layer_number > 2:

                return f"Inner Copper {layer_number}"

    # --------------------------------------------------------
    # OTHER
    # --------------------------------------------------------

    if (
        "drilldrawing" in name
        or "drill_drawing" in name
    ):

        return "Drill Drawing"

    if (
        "document" in name
        or "drawing" in name
    ):

        return "Document"

    return "Other Gerber"


def classify_drill_layer(
    filename: str
) -> str:

    name = filename.lower()

    if "npth" in name:
        return "NPTH Drill"

    if "pth" in name:
        return "PTH Drill"

    if "via" in name:
        return "Via Drill"

    if "blind" in name:
        return "Blind Via Drill"

    if "buried" in name:
        return "Buried Via Drill"

    return "Drill"


# ============================================================
# PCB SUMMARY
# ============================================================

def build_pcb_summary(
    project_files: List[Dict[str, Any]]
) -> Dict[str, Any]:

    layers = [
        item["layer"]
        for item in project_files
    ]

    copper_layers = []

    for layer in layers:

        if layer == "Top Copper":
            copper_layers.append(layer)

        elif layer == "Bottom Copper":
            copper_layers.append(layer)

        elif layer.startswith("Inner Copper"):
            copper_layers.append(layer)

    return {

        "copper_layers":
            len(copper_layers),

        "top_copper":
            "Top Copper" in layers,

        "bottom_copper":
            "Bottom Copper" in layers,

        "inner_layers":
            len([
                x for x in copper_layers
                if x.startswith(
                    "Inner Copper"
                )
            ]),

        "board_outline_found":
            (
                "Board Outline" in layers
                or "Board Profile" in layers
            ),

        "drill_files":
            len([
                x for x in project_files
                if x["category"] == "drill"
            ]),

        "top_solder_mask":
            "Top Solder Mask" in layers,

        "bottom_solder_mask":
            "Bottom Solder Mask" in layers,

        "top_silkscreen":
            "Top Silkscreen" in layers,

        "bottom_silkscreen":
            "Bottom Silkscreen" in layers
    }


# ============================================================
# GERBER FORMAT DETECTION
# ============================================================

def get_gerber_format(
    text: str
) -> Dict[str, Any]:

    result = {

        "x_integer": 2,
        "x_decimal": 4,
        "y_integer": 2,
        "y_decimal": 4,

        "units": "mm"
    }

    format_match = re.search(
        r"%FSL[AI]X(\d)(\d)Y(\d)(\d)\*%",
        text
    )

    if format_match:

        result["x_integer"] = int(
            format_match.group(1)
        )

        result["x_decimal"] = int(
            format_match.group(2)
        )

        result["y_integer"] = int(
            format_match.group(3)
        )

        result["y_decimal"] = int(
            format_match.group(4)
        )

    if "%MOIN" in text:

        result["units"] = "inch"

    elif "%MOMM" in text:

        result["units"] = "mm"

    return result


# ============================================================
# GERBER COORDINATE PARSER
# ============================================================

def parse_coordinate(
    value: str,
    decimal_places: int
) -> float:

    if not value:
        return 0.0

    sign = 1

    if value.startswith("-"):

        sign = -1
        value = value[1:]

    elif value.startswith("+"):

        value = value[1:]

    try:

        return (
            sign *
            int(value) /
            (10 ** decimal_places)
        )

    except Exception:

        return 0.0


def extract_gerber_coordinates(
    file_path: Path
) -> Dict[str, Any]:

    text = read_text_file(
        file_path
    )

    if not text:

        return {
            "points": [],
            "units": "mm"
        }

    fmt = get_gerber_format(
        text
    )

    x_decimal = fmt[
        "x_decimal"
    ]

    y_decimal = fmt[
        "y_decimal"
    ]

    units = fmt[
        "units"
    ]

    points = []

    current_x = None
    current_y = None

    coordinate_pattern = re.compile(
        r"(?:X([+-]?\d+))?"
        r"(?:Y([+-]?\d+))?"
        r"(?:D0?([123]))?"
    )

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if not line:
            continue

        if line.startswith("G04"):
            continue

        if line.startswith("%"):
            continue

        if "X" not in line and "Y" not in line:
            continue

        match = coordinate_pattern.search(
            line
        )

        if not match:
            continue

        x_raw = match.group(1)
        y_raw = match.group(2)
        d_code = match.group(3)

        if x_raw is not None:

            current_x = parse_coordinate(
                x_raw,
                x_decimal
            )

        if y_raw is not None:

            current_y = parse_coordinate(
                y_raw,
                y_decimal
            )

        if (
            current_x is not None
            and current_y is not None
        ):

            points.append({

                "x": current_x,
                "y": current_y,
                "d_code": d_code

            })

    # --------------------------------------------------------
    # CONVERT INCH TO MM
    # --------------------------------------------------------

    if units == "inch":

        for point in points:

            point["x"] *= 25.4
            point["y"] *= 25.4

        units = "mm"

    return {

        "points": points,

        "units": units,

        "format": {

            "x":
                f"{fmt['x_integer']}."
                f"{fmt['x_decimal']}",

            "y":
                f"{fmt['y_integer']}."
                f"{fmt['y_decimal']}"

        }
    }


# ============================================================
# CALCULATE BOUNDING BOX
# ============================================================

def calculate_bounds(
    points: List[Dict[str, Any]]
) -> Optional[Dict[str, float]]:

    if not points:
        return None

    xs = [
        p["x"]
        for p in points
    ]

    ys = [
        p["y"]
        for p in points
    ]

    if not xs or not ys:
        return None

    x_min = min(xs)
    x_max = max(xs)

    y_min = min(ys)
    y_max = max(ys)

    width = x_max - x_min
    height = y_max - y_min

    if width <= 0 or height <= 0:
        return None

    return {

        "x_min":
            round(x_min, 6),

        "x_max":
            round(x_max, 6),

        "y_min":
            round(y_min, 6),

        "y_max":
            round(y_max, 6),

        "width_mm":
            round(width, 6),

        "height_mm":
            round(height, 6),

        "area_mm2":
            round(
                width * height,
                4
            )
    }


# ============================================================
# OUTLINE PRIORITY
# ============================================================

def get_outline_priority(
    layer_name: str,
    filename: str
) -> int:

    name = filename.lower()

    if layer_name == "Board Outline":

        return 100

    if (
        "outline" in name
        or "edge.cuts" in name
    ):

        return 100

    if layer_name in {

        "Top Copper",
        "Bottom Copper"

    }:

        return 70

    if layer_name.startswith(
        "Inner Copper"
    ):

        return 60

    if layer_name in {

        "Top Solder Mask",
        "Bottom Solder Mask"

    }:

        return 50

    if layer_name in {

        "Top Silkscreen",
        "Bottom Silkscreen"

    }:

        return 40

    return 10


# ============================================================
# CLOSED CONTOUR DETECTION
# ============================================================

def count_closed_contours(
    file_path: Path
) -> int:

    text = read_text_file(
        file_path
    )

    if not text:
        return 0

    contours = 0

    start_x = None
    start_y = None

    current_x = None
    current_y = None

    fmt = get_gerber_format(
        text
    )

    for raw_line in text.splitlines():

        line = raw_line.strip()

        if (
            "X" not in line
            and "Y" not in line
        ):

            continue

        x_match = re.search(
            r"X([+-]?\d+)",
            line
        )

        y_match = re.search(
            r"Y([+-]?\d+)",
            line
        )

        if x_match:

            current_x = parse_coordinate(

                x_match.group(1),

                fmt["x_decimal"]

            )

        if y_match:

            current_y = parse_coordinate(

                y_match.group(1),

                fmt["y_decimal"]

            )

        if "D02" in line:

            start_x = current_x
            start_y = current_y

        elif "D01" in line:

            if (
                start_x is not None
                and start_y is not None
                and current_x is not None
                and current_y is not None
            ):

                tolerance = 0.001

                if (
                    abs(
                        current_x - start_x
                    ) <= tolerance
                    and
                    abs(
                        current_y - start_y
                    ) <= tolerance
                ):

                    contours += 1

                    start_x = None
                    start_y = None

    return contours


# ============================================================
# ANALYZE SINGLE OUTLINE CANDIDATE
# ============================================================

def analyze_outline_candidate(
    file_path: Path,
    layer_name: str
) -> Optional[Dict[str, Any]]:

    coordinate_data = (
        extract_gerber_coordinates(
            file_path
        )
    )

    points = coordinate_data[
        "points"
    ]

    if len(points) < 2:
        return None

    bounds = calculate_bounds(
        points
    )

    if not bounds:
        return None

    closed_contours = (
        count_closed_contours(
            file_path
        )
    )

    priority = get_outline_priority(
        layer_name,
        file_path.name
    )

    return {

        "file":
            file_path.name,

        "layer":
            layer_name,

        "priority":
            priority,

        "closed_contours":
            closed_contours,

        "width_mm":
            bounds["width_mm"],

        "height_mm":
            bounds["height_mm"],

        "area_mm2":
            bounds["area_mm2"],

        "bounds":
            bounds,

        "coordinate_format":
            coordinate_data[
                "format"
            ]
    }


# ============================================================
# BOARD OUTLINE ANALYSIS
# ============================================================
def analyze_gerber_geometry(file_path):
    """
    Analyze Gerber geometry using pcb-tools primitives.

    For board outlines we deliberately measure the geometric path centerline,
    not the aperture-expanded bounding box. A routed 73.20 mm outline must
    remain 73.20 mm even when the Gerber line has a non-zero stroke width.
    """
    file_path = Path(file_path)

    def arc_points(primitive, step_degrees=1.0):
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

        r1 = math.hypot(sx-cx, sy-cy)
        r2 = math.hypot(ex-cx, ey-cy)
        if r1 <= 1e-12 or r2 <= 1e-12:
            return [start, end]

        r = (r1+r2)/2.0
        a1 = math.atan2(sy-cy, sx-cx)
        a2 = math.atan2(ey-cy, ex-cx)
        direction = str(
            getattr(
                primitive,
                "direction",
                "counterclockwise"
            )
        ).lower()
        clockwise = (
            "clockwise" in direction
            and "counter" not in direction
        )

        if clockwise:
            sweep = a1-a2
            while sweep < 0:
                sweep += 2*math.pi
        else:
            sweep = a2-a1
            while sweep < 0:
                sweep += 2*math.pi

        if sweep < 1e-10:
            sweep = 2*math.pi

        steps = max(
            2,
            int(math.ceil(
                sweep / math.radians(step_degrees)
            ))
        )

        pts=[]
        for i in range(steps+1):
            t=i/steps
            angle = (
                a1-sweep*t
                if clockwise
                else a1+sweep*t
            )
            pts.append((
                cx+r*math.cos(angle),
                cy+r*math.sin(angle)
            ))

        pts[0]=(sx,sy)
        pts[-1]=(ex,ey)
        return pts

    def centerline_bounds(gerber_file):
        xs=[]
        ys=[]

        def add_point(point):
            if point is None:
                return
            try:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
            except Exception:
                pass

        def visit(primitive):
            name = type(primitive).__name__.lower()

            if "region" in name and hasattr(primitive, "primitives"):
                for child in getattr(
                    primitive,
                    "primitives",
                    []
                ) or []:
                    visit(child)
                return

            if "arc" in name:
                for point in arc_points(primitive):
                    add_point(point)
                return

            if hasattr(primitive, "start") and hasattr(
                primitive, "end"
            ):
                add_point(getattr(primitive, "start"))
                add_point(getattr(primitive, "end"))
                return

            # Flashes are real geometry, so include their aperture size.
            position = getattr(
                primitive,
                "position",
                None
            )
            diameter = getattr(
                primitive,
                "diameter",
                None
            )
            if position is not None and diameter is not None:
                try:
                    x,y=float(position[0]),float(position[1])
                    r=abs(float(diameter))/2.0
                    xs.extend([x-r,x+r])
                    ys.extend([y-r,y+r])
                except Exception:
                    pass

        for primitive in getattr(
            gerber_file,
            "primitives",
            []
        ):
            visit(primitive)

        if not xs or not ys:
            return None

        return {
            "x_min": min(xs),
            "x_max": max(xs),
            "y_min": min(ys),
            "y_max": max(ys),
            "width_mm": max(xs)-min(xs),
            "height_mm": max(ys)-min(ys),
            "area_mm2": (
                (max(xs)-min(xs))
                * (max(ys)-min(ys))
            ),
        }

    try:
        gerber_file = gerber.read(
            str(file_path)
        )

        if str(
            getattr(
                gerber_file,
                "units",
                "metric"
            )
        ).lower() == "inch":
            gerber_file.to_metric()

        bounds = centerline_bounds(
            gerber_file
        )

        if bounds and (
            bounds["width_mm"] > 0
            and bounds["height_mm"] > 0
        ):
            return {
                **bounds,
                "closed_contours":
                    count_closed_contours(
                        file_path
                    ),
                "point_count": len(
                    getattr(
                        gerber_file,
                        "primitives",
                        []
                    )
                ),
                "units": "mm",
                "method":
                    "pcb_tools_centerline_geometry",
            }

    except Exception as e:
        print(
            f"[GERBER GEOMETRY FALLBACK] "
            f"{file_path.name}: {e}"
        )

    return _legacy_analyze_gerber_geometry(
        file_path
    )
def _legacy_analyze_gerber_geometry(file_path):
    """
    Robust Gerber geometry parser.

    Supports:
      - X/Y coordinates separately or together
      - Modal coordinates
      - D01 draw
      - D02 move
      - D03 flash
      - Metric / inch
      - FSLAX formats
      - GKO / GM1 / GML board outlines

    Returns bounding-box geometry in mm.
    """

    try:
        with open(
            file_path,
            "r",
            encoding="utf-8",
            errors="ignore"
        ) as f:
            content = f.read()

    except Exception as e:
        print(
            f"[GERBER READ ERROR] "
            f"{file_path}: {e}"
        )
        return None

    if not content:
        return None

    upper = content.upper()

    # ============================================================
    # UNITS
    # ============================================================

    unit_multiplier = 1.0

    if "%MOIN" in upper:
        unit_multiplier = 25.4

    elif "%MOMM" in upper:
        unit_multiplier = 1.0

    # ============================================================
    # FORMAT
    # ============================================================

    format_match = re.search(
        r"%FSLAX(\d)(\d)Y(\d)(\d)",
        content,
        re.IGNORECASE
    )

    if not format_match:
        print(
            f"[GERBER FORMAT ERROR] "
            f"Format not found: {file_path.name}"
        )
        return None

    x_decimal = int(
        format_match.group(2)
    )

    y_decimal = int(
        format_match.group(4)
    )

    # ============================================================
    # COORDINATE CONVERSION
    # ============================================================

    def convert_coordinate(raw, decimals):

        if raw is None:
            return None

        raw = str(raw).strip()

        if not raw:
            return None

        sign = 1

        if raw.startswith("-"):
            sign = -1
            raw = raw[1:]

        elif raw.startswith("+"):
            raw = raw[1:]

        try:
            return (
                sign
                * int(raw)
                / (10 ** decimals)
                * unit_multiplier
            )

        except Exception:
            return None

    # ============================================================
    # BOUNDS
    # ============================================================

    min_x = None
    max_x = None
    min_y = None
    max_y = None

    # ============================================================
    # MODAL POSITION
    # ============================================================

    current_x = None
    current_y = None

    previous_x = None
    previous_y = None

    # ============================================================
    # CONTOUR TRACKING
    # ============================================================

    contour_start = None
    closed_contours = 0

    point_count = 0

    # Last D-code is modal in Gerber.
    current_operation = None

    # ============================================================
    # UPDATE BOUNDS SAFELY
    # ============================================================

    def add_point(x, y):

        nonlocal min_x
        nonlocal max_x
        nonlocal min_y
        nonlocal max_y
        nonlocal point_count

        if x is not None:

            if min_x is None or x < min_x:
                min_x = x

            if max_x is None or x > max_x:
                max_x = x

        if y is not None:

            if min_y is None or y < min_y:
                min_y = y

            if max_y is None or y > max_y:
                max_y = y

        if x is not None or y is not None:
            point_count += 1

    # ============================================================
    # PARSE COMMANDS
    # ============================================================

    commands = content.split("*")

    for raw_command in commands:

        command = raw_command.strip()

        if not command:
            continue

        # --------------------------------------------------------
        # Ignore parameter blocks
        # --------------------------------------------------------

        if command.startswith("%"):
            continue

        # --------------------------------------------------------
        # Ignore comments
        # --------------------------------------------------------

        if command.upper().startswith("G04"):
            continue

        # --------------------------------------------------------
        # Ignore aperture definitions and misc commands
        # --------------------------------------------------------

        if command.upper().startswith(
            (
                "G36",
                "G37",
                "G74",
                "G75",
                "M02",
                "M00",
            )
        ):
            continue

        # --------------------------------------------------------
        # D-code
        # --------------------------------------------------------

        d_match = re.search(
            r"D0?([123])",
            command,
            re.IGNORECASE
        )

        if d_match:
            current_operation = int(
                d_match.group(1)
            )

        # --------------------------------------------------------
        # Coordinates
        #
        # Examples:
        #
        # X732000
        # Y154000
        # X732000Y154000
        # X0
        # Y2000
        # --------------------------------------------------------

        x_match = re.search(
            r"X([+-]?\d+)",
            command,
            re.IGNORECASE
        )

        y_match = re.search(
            r"Y([+-]?\d+)",
            command,
            re.IGNORECASE
        )

        new_x = current_x
        new_y = current_y

        if x_match:

            parsed_x = convert_coordinate(
                x_match.group(1),
                x_decimal
            )

            if parsed_x is not None:
                new_x = parsed_x

        if y_match:

            parsed_y = convert_coordinate(
                y_match.group(1),
                y_decimal
            )

            if parsed_y is not None:
                new_y = parsed_y

        # --------------------------------------------------------
        # No coordinates = nothing to process
        # --------------------------------------------------------

        if (
            x_match is None
            and y_match is None
        ):
            continue

        # --------------------------------------------------------
        # We need both coordinates before drawing geometry.
        #
        # A command containing only X or only Y updates the modal
        # coordinate but does not create invalid None geometry.
        # --------------------------------------------------------

        old_x = current_x
        old_y = current_y

        current_x = new_x
        current_y = new_y

        if (
            current_x is None
            or current_y is None
        ):
            continue

        # --------------------------------------------------------
        # If D-code wasn't explicitly included, use modal D-code.
        # --------------------------------------------------------

        operation = current_operation

        if operation is None:
            continue

        # ========================================================
        # D02 = MOVE
        # ========================================================

        if operation == 2:

            add_point(
                current_x,
                current_y
            )

            contour_start = (
                current_x,
                current_y
            )

            previous_x = current_x
            previous_y = current_y

            continue

        # ========================================================
        # D01 = DRAW
        # ========================================================

        if operation == 1:

            # First drawing point
            if previous_x is None:

                previous_x = current_x
                previous_y = current_y

                add_point(
                    current_x,
                    current_y
                )

                if contour_start is None:
                    contour_start = (
                        current_x,
                        current_y
                    )

                continue

            # Add both endpoints
            add_point(
                previous_x,
                previous_y
            )

            add_point(
                current_x,
                current_y
            )

            # ----------------------------------------------------
            # Closed contour
            # ----------------------------------------------------

            if contour_start is None:

                contour_start = (
                    previous_x,
                    previous_y
                )

            if (
                abs(
                    current_x
                    - contour_start[0]
                ) < 1e-9
                and
                abs(
                    current_y
                    - contour_start[1]
                ) < 1e-9
            ):

                closed_contours += 1

                contour_start = None

            previous_x = current_x
            previous_y = current_y

            continue

        # ========================================================
        # D03 = FLASH
        # ========================================================

        if operation == 3:

            add_point(
                current_x,
                current_y
            )

            previous_x = current_x
            previous_y = current_y

            continue

    # ============================================================
    # VALIDATE
    # ============================================================

    if (
        min_x is None
        or max_x is None
        or min_y is None
        or max_y is None
    ):
        return None

    width_mm = max_x - min_x
    height_mm = max_y - min_y

    if width_mm <= 0 or height_mm <= 0:
        return None

    # ============================================================
    # RETURN
    # ============================================================

    return {
        "x_min": min_x,
        "x_max": max_x,

        "y_min": min_y,
        "y_max": max_y,

        "width_mm": width_mm,
        "height_mm": height_mm,

        "closed_contours":
            closed_contours,

        "point_count":
            point_count,

        "units":
            "mm",
    }


def analyze_project_board(extracted_path):
    """
    ROBUST PCB BOARD OUTLINE DETECTION

    The board outline may be:
        - a dedicated outline/profile Gerber
        - GKO / GML / GM1 / GMB
        - Top/Bottom Copper
        - Top/Bottom Silkscreen
        - Top/Bottom Solder Mask
        - Top/Bottom Paste
        - Mechanical/document layer
        - another Gerber layer

    IMPORTANT:
    Layer classification and outline detection are independent.

    Example:
        Top Silkscreen file containing board perimeter
        remains:
            layer = "Top Silkscreen"

        while board_analysis reports:
            outline_file = that file
            source_layer = "Top Silkscreen"
    """

    extracted_path = Path(extracted_path)

    # ------------------------------------------------------------
    # GET THE SAME GLOBAL FILE CLASSIFICATION USED EVERYWHERE
    # ------------------------------------------------------------

    project_files = get_project_files(
        extracted_path
    )

    candidates = []

    # ------------------------------------------------------------
    # OUTLINE NAME / EXTENSION INDICATORS
    # ------------------------------------------------------------

    outline_keywords = (
        "board outline",
        "board_outline",
        "boardoutline",
        "outline",
        "edge cuts",
        "edge_cuts",
        "edgecuts",
        "edge-cut",
        "edgecut",
        "profile",
        "routing",
        "route",
        "mechanical",
        "profile",
        "dimension",
        "dimensions",
    )

    outline_extensions = {
        ".gko",
        ".gm1",
        ".gm2",
        ".gml",
        ".gmb",
        ".gbr",
        ".ger",
        ".outline",
        ".edge",
    }

    # ------------------------------------------------------------
    # SCAN EVERY CLASSIFIED GERBER FILE
    #
    # DO NOT FILTER BY EXTENSION HERE.
    #
    # This is the critical fix.
    # ------------------------------------------------------------

    for item in project_files:

        if item.get("category") != "gerber":
            continue

        filename = item.get(
            "filename",
            ""
        )

        if not filename:
            continue

        file_path = Path(
            item.get("path", "")
        )

        if not file_path.exists():
            continue

        layer_name = str(
            item.get("layer") or "Unknown"
        )

        filename_lower = filename.lower()
        extension = file_path.suffix.lower()

        # --------------------------------------------------------
        # EXPLICIT OUTLINE INFORMATION
        # --------------------------------------------------------

        is_explicit_outline = (
            layer_name.lower()
            in {
                "board outline",
                "board profile",
                "profile",
                "edge cuts",
            }
        )

        filename_outline = any(
            keyword in filename_lower
            for keyword in outline_keywords
        )

        extension_outline = (
            extension in outline_extensions
            and extension in {
                ".gko",
                ".gm1",
                ".gm2",
                ".gml",
                ".gmb",
            }
        )

        # --------------------------------------------------------
        # ANALYZE ACTUAL GERBER GEOMETRY
        # --------------------------------------------------------

        try:

            result = analyze_gerber_geometry(
                file_path
            )

        except Exception as e:

            print(
                f"[BOARD ANALYSIS ERROR] "
                f"{filename}: {e}"
            )

            continue

        if not result:
            continue

        try:

            width = float(
                result.get(
                    "width_mm",
                    0
                )
            )

            height = float(
                result.get(
                    "height_mm",
                    0
                )
            )

        except Exception:

            continue

        if (
            width <= 0
            or height <= 0
        ):
            continue

        closed_contours = int(
            result.get(
                "closed_contours",
                0
            )
        )

        point_count = int(
            result.get(
                "point_count",
                0
            )
        )

        # --------------------------------------------------------
        # GEOMETRIC OUTLINE SCORE
        # --------------------------------------------------------

        score = 0

        detection_method = (
            "geometry_scan"
        )

        # Dedicated / explicit outline
        if is_explicit_outline:
            score += 100
            detection_method = (
                "classified_outline_layer"
            )

        # Filename says outline/profile
        if filename_outline:
            score += 90

            if detection_method == "geometry_scan":
                detection_method = (
                    "outline_filename"
                )

        # Standard outline extension
        if extension_outline:
            score += 80

            if detection_method == "geometry_scan":
                detection_method = (
                    "outline_extension"
                )

        # --------------------------------------------------------
        # CLOSED CONTOUR IS VERY STRONG EVIDENCE
        # --------------------------------------------------------

        if closed_contours >= 1:

            score += 60

            if detection_method == "geometry_scan":
                detection_method = (
                    "closed_contour"
                )

        elif closed_contours == 0:

            # Still allow a geometry candidate.
            # Some CAD systems export segmented/open perimeter
            # geometry or use arcs in a way our contour counter
            # cannot close reliably.

            if point_count >= 4:
                score += 10

        # --------------------------------------------------------
        # BOARD-LIKE GEOMETRY
        # --------------------------------------------------------

        area = width * height

        if area > 1.0:
            score += 5

        if area > 10.0:
            score += 5

        # --------------------------------------------------------
        # ASPECT RATIO
        # --------------------------------------------------------

        shortest = min(
            width,
            height
        )

        longest = max(
            width,
            height
        )

        if shortest > 0:

            aspect_ratio = (
                longest / shortest
            )

        else:

            aspect_ratio = 999.0

        # Most PCB profiles are not extremely tiny.
        if (
            shortest >= 2.0
            and longest >= 5.0
        ):
            score += 10

        # --------------------------------------------------------
        # DO NOT THROW AWAY A GEOMETRIC CANDIDATE
        #
        # This is particularly important when outline is on:
        #   Top Silk
        #   Copper
        #   Mask
        #   Paste
        # --------------------------------------------------------

        if (
            closed_contours >= 1
            or is_explicit_outline
            or filename_outline
            or extension_outline
        ):

            candidates.append({

                "file":
                    filename,

                "path":
                    str(file_path),

                "layer":
                    layer_name,

                "priority":
                    score,

                "method":
                    detection_method,

                "width_mm":
                    width,

                "height_mm":
                    height,

                "area_mm2":
                    area,

                "x_min":
                    result.get("x_min"),

                "x_max":
                    result.get("x_max"),

                "y_min":
                    result.get("y_min"),

                "y_max":
                    result.get("y_max"),

                "closed_contours":
                    closed_contours,

                "point_count":
                    point_count,

                "aspect_ratio":
                    round(
                        aspect_ratio,
                        4
                    ),

                "is_explicit_outline":
                    is_explicit_outline,

                "is_filename_outline":
                    filename_outline,

                "is_outline_extension":
                    extension_outline,
            })

    # ============================================================
    # NO OUTLINE CANDIDATE
    # ============================================================

    if not candidates:

        return {
            "outline_found":
                False,

            "outline_file":
                None,

            "source_layer":
                None,

            "confidence":
                0,

            "method":
                None,

            "dimensions":
                None,

            "candidates_found":
                0,

            "candidates":
                [],
        }

    # ============================================================
    # SORT CANDIDATES
    #
    # Highest score wins.
    #
    # If scores are equal:
    #   1. closed contours
    #   2. area
    # ============================================================

    candidates.sort(
        key=lambda c: (
            c.get(
                "priority",
                0
            ),
            c.get(
                "closed_contours",
                0
            ),
            c.get(
                "area_mm2",
                0
            ),
        ),
        reverse=True
    )

    best = candidates[0]

    # ============================================================
    # CONFIDENCE
    # ============================================================

    priority = int(
        best.get(
            "priority",
            0
        )
    )

    if priority >= 100:
        confidence = 99

    elif priority >= 90:
        confidence = 97

    elif priority >= 80:
        confidence = 95

    elif priority >= 60:
        confidence = 90

    elif priority >= 40:
        confidence = 80

    else:
        confidence = 60

    # ============================================================
    # FINAL DIMENSIONS
    # ============================================================

    width_mm = float(
        best["width_mm"]
    )

    height_mm = float(
        best["height_mm"]
    )

    x_min = best.get(
        "x_min"
    )

    x_max = best.get(
        "x_max"
    )

    y_min = best.get(
        "y_min"
    )

    y_max = best.get(
        "y_max"
    )

    # ============================================================
    # RETURN
    # ============================================================

    return {

        "outline_found":
            True,

        "outline_file":
            best["file"],

        # IMPORTANT:
        # This tells us which REAL PCB layer contained
        # the outline geometry.
        "source_layer":
            best.get(
                "layer"
            ),

        "confidence":
            confidence,

        "method":
            best.get(
                "method"
            ),

        "dimensions": {

            "units":
                "mm",

            "x_min":
                (
                    round(
                        float(x_min),
                        5
                    )
                    if x_min is not None
                    else None
                ),

            "x_max":
                (
                    round(
                        float(x_max),
                        5
                    )
                    if x_max is not None
                    else None
                ),

            "y_min":
                (
                    round(
                        float(y_min),
                        5
                    )
                    if y_min is not None
                    else None
                ),

            "y_max":
                (
                    round(
                        float(y_max),
                        5
                    )
                    if y_max is not None
                    else None
                ),

            "width_mm":
                round(
                    width_mm,
                    5
                ),

            "height_mm":
                round(
                    height_mm,
                    5
                ),

            "area_mm2":
                round(
                    width_mm
                    * height_mm,
                    4
                ),
        },

        "candidates_found":
            len(candidates),

        "candidates":
            candidates,
    }

# ============================================================
# DRILL ANALYSIS
# ============================================================

def parse_drill_file(file_path: Path) -> Dict[str, Any]:
    """
    Parse Excellon using pcb-tools first.

    This correctly handles units, zero suppression, absolute/incremental
    notation, tool selection and routed slots. Text parsing is retained
    only as a fallback.
    """
    file_path = Path(file_path)

    # Content-first: detect legacy/headerless NC drill before pcb-tools.
    # This avoids a misleading parser exception for valid TAP output.
    try:
        legacy = parse_headerless_nc_drill(file_path)
    except Exception as legacy_error:
        legacy = None
        print(f"[LEGACY TAP PARSER] {file_path.name}: {legacy_error}")

    if legacy is not None:
        tools = legacy.get("tools", [])
        diameters = [float(t["diameter"]) for t in tools if t.get("diameter") is not None]
        print(
            f"[LEGACY TAP PARSER] {file_path.name}: "
            f"parsed {legacy.get('drill_count', 0)} hits, {len(tools)} tools"
        )
        return {
            "total_hits": legacy.get("drill_count", 0),
            "total_features": legacy.get("drill_count", 0),
            "slots": 0,
            "tool_count": len(tools),
            "minimum_drill": min(diameters) if diameters else None,
            "maximum_drill": max(diameters) if diameters else None,
            "tools": tools,
            "method": "legacy_headerless_tap",
        }

    try:
        drill_file = gerber.read(str(file_path))

        if str(
            getattr(
                drill_file,
                "units",
                "metric"
            )
        ).lower() == "inch":
            drill_file.to_metric()

        tools = {}
        hits = 0
        slots = 0

        excellon_hits = getattr(drill_file, "hits", None) or []
        if excellon_hits:
            for hit in excellon_hits:
                tool = getattr(hit, "tool", None)
                number = getattr(tool, "number", None)
                diameter = getattr(tool, "diameter", None)

                if number is not None:
                    tool_name = f"T{int(number):02d}"
                else:
                    tool_name = "Unknown"

                entry = tools.setdefault(
                    tool_name,
                    {
                        "diameter": (
                            float(diameter)
                            if diameter is not None
                            else None
                        ),
                        "hits": 0,
                        "slots": 0,
                    }
                )

                entry["hits"] += 1

                hit_name = type(hit).__name__.lower()
                if "slot" in hit_name:
                    entry["slots"] += 1
                    slots += 1
                else:
                    hits += 1
        else:
            # Handle Gerber format drill files (RS-274X / Gerber X2 drill files)
            for prim in getattr(drill_file, "primitives", []) or []:
                dia = getattr(prim, "diameter", getattr(getattr(prim, "aperture", None), "diameter", None))
                if dia is None:
                    continue
                dia_val = float(dia)
                if dia_val <= 0:
                    continue
                ap_code = getattr(getattr(prim, "aperture", None), "dcode", None)
                tool_name = f"D{ap_code}" if ap_code else f"{dia_val:.3f}mm"
                entry = tools.setdefault(
                    tool_name,
                    {
                        "diameter": dia_val,
                        "hits": 0,
                        "slots": 0,
                    }
                )
                entry["hits"] += 1
                hits += 1

        tool_list = []
        diameters = []

        for tool_name, info in tools.items():
            diameter = info.get("diameter")
            if diameter is not None:
                diameter = round(float(diameter), 4)
                diameters.append(diameter)

            tool_list.append({
                "tool": tool_name,
                "diameter": diameter,
                "hits": int(info.get("hits", 0)),
                "slots": int(info.get("slots", 0)),
            })

        tool_list.sort(
            key=lambda item: (
                float(item["diameter"])
                if item["diameter"] is not None
                else float("inf")
            )
        )

        return {
            "total_hits": hits,
            "total_features": hits + slots,
            "slots": slots,
            "tool_count": len(tool_list),
            "minimum_drill": (
                min(diameters)
                if diameters
                else None
            ),
            "maximum_drill": (
                max(diameters)
                if diameters
                else None
            ),
            "tools": tool_list,
            "method": "pcb_tools_excellon",
        }

    except Exception as e:
        print(
            f"[DRILL PARSER FALLBACK] "
            f"{file_path.name}: {e}"
        )

    # ------------------------------------------------------------
    # FALLBACK TEXT PARSER
    # ------------------------------------------------------------
    text = read_text_file(file_path)

    if not text:
        return {
            "total_hits": 0,
            "total_features": 0,
            "slots": 0,
            "tool_count": 0,
            "minimum_drill": None,
            "maximum_drill": None,
            "tools": [],
            "method": "empty",
        }

    tools = {}
    current_tool = None

    for match in re.finditer(
        r"T(\d+)\s*C([0-9.]+)",
        text,
        re.IGNORECASE
    ):
        tool_name = "T" + match.group(1).zfill(2)
        try:
            diameter = float(match.group(2))
        except Exception:
            continue

        tools[tool_name] = {
            "diameter": diameter,
            "hits": 0,
            "slots": 0,
        }

    coordinate_re = re.compile(
        r"(?:^|[\s;])"
        r"(?:X[+-]?\d+(?:\.\d+)?)?"
        r"(?:Y[+-]?\d+(?:\.\d+)?)?"
        r"(?:\s*)$",
        re.IGNORECASE
    )

    total_hits = 0
    slots = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith(";"):
            continue

        tool_match = re.match(
            r"^T(\d+)(?:\s|$)",
            line,
            re.IGNORECASE
        )
        if tool_match and "C" not in line.upper():
            current_tool = "T" + tool_match.group(1).zfill(2)
            continue

        if current_tool not in tools:
            continue

        if (
            re.search(r"[XY][+-]?\d+(?:\.\d+)?", line, re.I)
            and coordinate_re.search(line.replace("*", ""))
        ):
            tools[current_tool]["hits"] += 1
            total_hits += 1

    tool_list = []
    diameters = []

    for tool_name, info in tools.items():
        diameter = round(
            float(info["diameter"]),
            4
        )
        diameters.append(diameter)

        tool_list.append({
            "tool": tool_name,
            "diameter": diameter,
            "hits": info["hits"],
            "slots": 0,
        })

    tool_list.sort(
        key=lambda item: item["diameter"]
    )

    return {
        "total_hits": total_hits,
        "total_features": total_hits,
        "slots": slots,
        "tool_count": len(tool_list),
        "minimum_drill": min(diameters) if diameters else None,
        "maximum_drill": max(diameters) if diameters else None,
        "tools": tool_list,
        "method": "text_fallback",
    }


def analyze_project_drills(
    extracted_path: Path
) -> Dict[str, Any]:

    project_files = get_project_files(
        extracted_path
    )

    results = []

    total_hits = 0
    total_features = 0
    total_slots = 0

    all_minimums = []
    all_maximums = []

    for item in project_files:
        if item["category"] != "drill":
            continue

        file_path = Path(
            item["path"]
        )

        analysis = parse_drill_file(
            file_path
        )

        results.append({
            "filename": file_path.name,
            "layer": item.get("layer", "Drill"),
            "analysis": analysis,
        })

        total_hits += int(
            analysis.get("total_hits", 0)
        )
        total_features += int(
            analysis.get("total_features", 0)
        )
        total_slots += int(
            analysis.get("slots", 0)
        )

        minimum = analysis.get(
            "minimum_drill"
        )
        maximum = analysis.get(
            "maximum_drill"
        )

        if minimum is not None:
            all_minimums.append(
                float(minimum)
            )

        if maximum is not None:
            all_maximums.append(
                float(maximum)
            )

    return {
        "drill_files": len(results),
        "total_drill_hits": total_hits,
        "total_drill_features": total_features,
        "total_slots": total_slots,
        "minimum_drill": (
            min(all_minimums)
            if all_minimums
            else None
        ),
        "maximum_drill": (
            max(all_maximums)
            if all_maximums
            else None
        ),
        "files": results,
    }


# ============================================================
# BUILD PCB LAYER STACK
# ============================================================

def build_layer_stack(
    project_files: List[Dict[str, Any]]
) -> Dict[str, Any]:

    detected_layers = [

        item["layer"]

        for item in project_files

    ]

    stack = []

    # --------------------------------------------------------
    # TOP SIDE
    # --------------------------------------------------------

    if "Top Silkscreen" in detected_layers:

        stack.append({

            "name":
                "Top Silkscreen",

            "type":
                "silkscreen",

            "side":
                "top"

        })

    if "Top Solder Mask" in detected_layers:

        stack.append({

            "name":
                "Top Solder Mask",

            "type":
                "solder_mask",

            "side":
                "top"

        })

    # --------------------------------------------------------
    # COPPER
    # --------------------------------------------------------

    if "Top Copper" in detected_layers:

        stack.append({

            "name":
                "Top Copper",

            "type":
                "copper",

            "side":
                "top"

        })

    # --------------------------------------------------------
    # INNER COPPER
    # --------------------------------------------------------

    inner_layers = [

        layer

        for layer
        in detected_layers

        if layer.startswith(
            "Inner Copper"
        )

    ]

    inner_layers.sort()

    for layer in inner_layers:

        stack.append({

            "name":
                layer,

            "type":
                "copper",

            "side":
                "inner"

        })

    # --------------------------------------------------------
    # CORE
    # --------------------------------------------------------

    if (
        "Top Copper" in detected_layers
        and
        "Bottom Copper" in detected_layers
    ):

        stack.append({

            "name":
                "FR4 Core",

            "type":
                "substrate",

            "side":
                "inner"

        })

    # --------------------------------------------------------
    # BOTTOM SIDE
    # --------------------------------------------------------

    if "Bottom Copper" in detected_layers:

        stack.append({

            "name":
                "Bottom Copper",

            "type":
                "copper",

            "side":
                "bottom"

        })

    if "Bottom Solder Mask" in detected_layers:

        stack.append({

            "name":
                "Bottom Solder Mask",

            "type":
                "solder_mask",

            "side":
                "bottom"

        })

    if "Bottom Silkscreen" in detected_layers:

        stack.append({

            "name":
                "Bottom Silkscreen",

            "type":
                "silkscreen",

            "side":
                "bottom"

        })

    return {

        "total_copper_layers":

            len([

                layer

                for layer
                in stack

                if layer["type"]
                == "copper"

            ]),

        "stack":
            stack

    }

# ============================================================
# DFM CHECK HELPER
# ============================================================

def create_dfm_check(
    rule,
    status,
    message
) -> Dict[str, Any]:

    return {
        "rule": rule,
        "status": status,
        "message": message
    }

# ============================================================
# BASIC DFM CHECKER
# ============================================================
# ============================================================
# COPPER LAYER ANALYSIS
# ============================================================

def analyze_copper_layers(extracted_dir, files):

    layers = []

    minimum_trace_width = None
    minimum_spacing = None

    total_traces = 0
    total_comparisons = 0

    for file_info in files:

        filename = file_info.get("filename")
        layer_name = file_info.get("layer")
        category = file_info.get("category")

        # Only analyze copper Gerber layers
        if category != "gerber":
            continue

        if layer_name not in [
            "Top Copper",
            "Bottom Copper"
        ]:
            continue

        file_path = os.path.join(
            extracted_dir,
            filename
        )

        if not os.path.exists(file_path):
            continue

        # --------------------------------------------
        # TRACE WIDTH ANALYSIS
        # --------------------------------------------

        try:

            trace_result = analyze_copper_geometry(
                file_path
            )

        except Exception as e:

            trace_result = {
                "success": False,
                "minimum_trace_width": None,
                "trace_count": 0,
                "widths": [],
                "errors": [str(e)]
            }

        # --------------------------------------------
        # COPPER SPACING ANALYSIS
        # --------------------------------------------

        try:

            spacing_result = analyze_copper_spacing(
                file_path
            )

        except Exception as e:

            spacing_result = {
                "success": False,
                "minimum_spacing": None,
                "comparisons": 0,
                "errors": [str(e)]
            }

        # --------------------------------------------
        # UPDATE GLOBAL VALUES
        # --------------------------------------------

        trace_width = trace_result.get(
            "minimum_trace_width"
        )

        spacing = spacing_result.get(
            "minimum_spacing"
        )

        if trace_width is not None:

            if (
                minimum_trace_width is None
                or trace_width < minimum_trace_width
            ):

                minimum_trace_width = trace_width

        if spacing is not None:

            if (
                minimum_spacing is None
                or spacing < minimum_spacing
            ):

                minimum_spacing = spacing

        total_traces += trace_result.get(
            "trace_count",
            0
        )

        total_comparisons += spacing_result.get(
            "comparisons",
            0
        )

        # --------------------------------------------
        # STORE LAYER RESULT
        # --------------------------------------------



    return {

        "layers_analyzed":
            len(layers),

        "minimum_trace_width":
            minimum_trace_width,

        "minimum_spacing":
            minimum_spacing,

        "total_traces":
            total_traces,

        "total_spacing_comparisons":
            total_comparisons,

        "layers":
            layers

    }
def run_dfm_checks(
    pcb_summary,
    drill_analysis,
    board_analysis,
    copper_analysis=None
) -> Dict[str, Any]:

    checks = []

    # --------------------------------------------------------
    # BOARD OUTLINE
    # --------------------------------------------------------

    if not board_analysis.get(
        "outline_found"
    ):

        checks.append({

            "rule":
                "Board Outline",

            "status":
                "error",

            "message":
                "No reliable board outline detected."

        })

    else:

        confidence = board_analysis.get(
            "confidence",
            0
        )

        if confidence < 70:

            checks.append({

                "rule":
                    "Board Outline",

                "status":
                    "warning",

                "message":
                    "Board outline was detected from fallback geometry. Manual verification recommended."

            })

        else:

            checks.append({

                "rule":
                    "Board Outline",

                "status":
                    "pass",

                "message":
                    "Board outline detected successfully."

            })

    # --------------------------------------------------------
    # COPPER LAYERS
    # --------------------------------------------------------

    if (
        pcb_summary[
            "copper_layers"
        ] == 0
    ):

        checks.append({

            "rule":
                "Copper Layers",

            "status":
                "error",

            "message":
                "No copper layers detected."

        })

    else:

        checks.append({

            "rule":
                "Copper Layers",

            "status":
                "pass",

            "message":
                f"{pcb_summary['copper_layers']} copper layer(s) detected."

        })

    # --------------------------------------------------------
    # DRILL
    # --------------------------------------------------------

    if (
        drill_analysis[
            "drill_files"
        ] == 0
    ):

        checks.append({

            "rule":
                "Drill Files",

            "status":
                "warning",

            "message":
                "No drill file detected."

        })

    else:

        checks.append({

            "rule":
                "Drill Files",

            "status":
                "pass",

            "message":
                f"{drill_analysis['drill_files']} drill file(s) detected."

        })

    # --------------------------------------------------------
    # MINIMUM DRILL
    # --------------------------------------------------------

    minimum_drill = (
        drill_analysis.get(
            "minimum_drill"
        )
    )

    if minimum_drill is not None:

        if minimum_drill < 0.20:

            checks.append({

                "rule":
                    "Minimum Drill",

                "status":
                    "warning",

                "message":
                    f"Minimum drill is {minimum_drill} mm. Manufacturing capability should be verified."

            })

        else:

            checks.append({

                "rule":
                    "Minimum Drill",

                "status":
                    "pass",

                "message":
                    f"Minimum drill is {minimum_drill} mm."

            })
    # MINIMUM TRACE WIDTH

    minimum_trace_width = copper_analysis.get(
        "minimum_trace_width"
    )

    if minimum_trace_width is None:

        checks.append(
            create_dfm_check(
                "Minimum Trace Width",
                "warning",
                "Could not determine minimum trace width."
            )
        )

    elif minimum_trace_width < 0.10:

        checks.append(
            create_dfm_check(
                "Minimum Trace Width",
                "error",
                f"Minimum trace width is {minimum_trace_width} mm. "
                "Below manufacturing capability."
            )
        )

    elif minimum_trace_width < 0.15:

        checks.append(
            create_dfm_check(
                "Minimum Trace Width",
                "warning",
                f"Minimum trace width is {minimum_trace_width} mm. "
                "Requires special manufacturing capability."
            )
        )

    else:

        checks.append(
            create_dfm_check(
                "Minimum Trace Width",
                "pass",
                f"Minimum trace width is {minimum_trace_width} mm."
            )
        )
        
        # --------------------------------------------------------
    # MINIMUM COPPER SPACING
    # --------------------------------------------------------

    minimum_spacing = None

    if copper_analysis:

        minimum_spacing = copper_analysis.get(
            "minimum_spacing"
        )

    if minimum_spacing is None:

        checks.append(
            create_dfm_check(
                "Minimum Copper Spacing",
                "warning",
                "Could not determine minimum copper spacing."
            )
        )

    elif minimum_spacing < 0.075:

        checks.append(
            create_dfm_check(
                "Minimum Copper Spacing",
                "error",
                f"Minimum copper spacing is {minimum_spacing} mm. "
                "Below manufacturing capability."
            )
        )

    elif minimum_spacing < 0.10:

        checks.append(
            create_dfm_check(
                "Minimum Copper Spacing",
                "warning",
                f"Minimum copper spacing is {minimum_spacing} mm. "
                "Requires special manufacturing capability."
            )
        )

    else:

        checks.append(
            create_dfm_check(
                "Minimum Copper Spacing",
                "pass",
                f"Minimum copper spacing is {minimum_spacing} mm."
            )
        )
    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    errors = len([

        x for x in checks

        if x["status"] == "error"

    ])

    warnings = len([

        x for x in checks

        if x["status"] == "warning"

    ])

    passes = len([

        x for x in checks

        if x["status"] == "pass"

    ])

    if errors > 0:

        overall_status = "fail"

    elif warnings > 0:

        overall_status = "warning"

    else:

        overall_status = "pass"

    return {

        "overall_status":
            overall_status,

        "summary": {

            "passes":
                passes,

            "warnings":
                warnings,

            "errors":
                errors

        },

        "checks":
            checks

    }


# ============================================================
# IMAGE RENDERING
# NO CAIRO REQUIRED
# ============================================================

def render_points_to_image(
    points: List[Dict[str, Any]],
    output_path: Path,
    width: int = 1200,
    height: int = 800,
    padding: int = 50
):

    if not points:
        return False

    bounds = calculate_bounds(
        points
    )

    if not bounds:
        return False

    image = Image.new(

        "RGB",

        (
            width,
            height
        ),

        "white"

    )

    draw = ImageDraw.Draw(
        image
    )

    x_min = bounds["x_min"]
    x_max = bounds["x_max"]

    y_min = bounds["y_min"]
    y_max = bounds["y_max"]

    board_width = (
        x_max - x_min
    )

    board_height = (
        y_max - y_min
    )

    if board_width <= 0:
        board_width = 1

    if board_height <= 0:
        board_height = 1

    scale_x = (

        (width - 2 * padding)

        /

        board_width

    )

    scale_y = (

        (height - 2 * padding)

        /

        board_height

    )

    scale = min(
        scale_x,
        scale_y
    )

    previous = None

    for point in points:

        px = (

            padding +

            (
                point["x"] - x_min
            )

            * scale

        )

        py = (

            height -

            padding -

            (
                point["y"] - y_min
            )

            * scale

        )

        if (
            point.get("d_code")
            == "2"
        ):

            previous = (
                px,
                py
            )

            continue

        if previous is not None:

            draw.line(

                [
                    previous,
                    (
                        px,
                        py
                    )
                ],

                fill="black",

                width=2

            )

        previous = (
            px,
            py
        )

    image.save(
        output_path
    )

    return True


def render_gerber_layers(
    extracted_path: Path,
    project_id: str
) -> Dict[str, Any]:

    project_files = get_project_files(
        extracted_path
    )

    render_dir = (
        PROJECT_DIR
        / project_id
        / "renders"
    )

    render_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    renders = []

    for item in project_files:

        if item["category"] != "gerber":
            continue

        file_path = Path(
            item["path"]
        )

        coordinate_data = (
            extract_gerber_coordinates(
                file_path
            )
        )

        points = coordinate_data[
            "points"
        ]

        if len(points) < 2:
            continue

        image_name = (

            file_path.stem

            + ".png"

        )

        output_path = (

            render_dir

            / image_name

        )

        success = (
            render_points_to_image(

                points,

                output_path

            )
        )

        if success:

            renders.append({

                "filename":
                    file_path.name,

                "layer":
                    item["layer"],

                "image":
                    f"/projects/{project_id}/renders/{image_name}"

            })

    return {

        "total_renders":
            len(renders),

        "layers":
            renders

    }


# ============================================================
# SIMPLE 3D PCB PREVIEW
# ============================================================

def generate_3d_preview(
    board_analysis: Dict[str, Any],
    project_id: str
) -> Optional[str]:

    if not board_analysis.get(
        "outline_found"
    ):

        return None

    dimensions = board_analysis.get(
        "dimensions"
    )

    if not dimensions:
        return None

    board_width = (
        dimensions[
            "width_mm"
        ]
    )

    board_height = (
        dimensions[
            "height_mm"
        ]
    )

    if board_width <= 0 or board_height <= 0:
        return None

    render_dir = (

        PROJECT_DIR

        / project_id

        / "renders"

    )

    render_dir.mkdir(

        parents=True,

        exist_ok=True

    )

    image_width = 1000
    image_height = 700

    image = Image.new(

        "RGB",

        (
            image_width,
            image_height
        ),

        "white"

    )

    draw = ImageDraw.Draw(
        image
    )

    max_width = 700
    max_height = 350

    scale = min(

        max_width / board_width,

        max_height / board_height

    )

    w = board_width * scale
    h = board_height * scale

    x = (
        image_width - w
    ) / 2

    y = (
        image_height - h
    ) / 2 - 30

    depth = 40

    # Front board

    draw.polygon(

        [

            (x, y),

            (x + w, y),

            (x + w, y + h),

            (x, y + h)

        ],

        fill=(45, 125, 70),

        outline="black"

    )

    # Right side

    draw.polygon(

        [

            (x + w, y),

            (x + w + depth, y - depth),

            (x + w + depth, y + h - depth),

            (x + w, y + h)

        ],

        fill=(30, 85, 45),

        outline="black"

    )

    # Bottom side

    draw.polygon(

        [

            (x, y + h),

            (x + w, y + h),

            (x + w + depth, y + h - depth),

            (x + depth, y + h - depth)

        ],

        fill=(35, 100, 55),

        outline="black"

    )

    output_path = (

        render_dir

        / "pcb_3d_preview.png"

    )

    image.save(
        output_path
    )

    return (

        f"/projects/{project_id}/renders/pcb_3d_preview.png"

    )


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def home():
    dfm_file = Path(__file__).resolve().parent / "dfm.html"

    if not dfm_file.exists():
        raise HTTPException(
            status_code=404,
            detail="DFM dashboard file not found: dfm.html"
        )

    return FileResponse(
        str(dfm_file),
        media_type="text/html"
    )


# ============================================================
# MAIN PCB ANALYSIS API
# ============================================================
# ============================================================
# DFM GEOMETRY ANALYSIS
# MINIMUM TRACE WIDTH
# MINIMUM COPPER SPACING
# ============================================================

# ============================================================
# COPPER GEOMETRY ANALYSIS
# ============================================================

def analyze_copper_geometry(file_path):

    result = {
        "success": False,
        "minimum_trace_width": None,
        "trace_count": 0,
        "widths": [],
        "errors": []
    }

    try:

        import gerber

        layer = gerber.read(file_path)

        widths = []

        for primitive in layer.primitives:

            primitive_type = type(primitive).__name__

            # ------------------------------------------------
            # LINE / ARC WITH APERTURE
            # ------------------------------------------------

            if primitive_type in ["Line", "Arc"]:

                aperture = getattr(
                    primitive,
                    "aperture",
                    None
                )

                if aperture is None:
                    continue

                aperture_type = type(
                    aperture
                ).__name__

                width = None

                # --------------------------------------------
                # CIRCULAR APERTURE
                # --------------------------------------------

                if aperture_type == "Circle":

                    width = getattr(
                        aperture,
                        "diameter",
                        None
                    )

                # --------------------------------------------
                # RECTANGULAR APERTURE
                # --------------------------------------------

                elif aperture_type == "Rectangle":

                    width = getattr(
                        aperture,
                        "width",
                        None
                    )

                    if width is None:

                        width = getattr(
                            aperture,
                            "height",
                            None
                        )

                # --------------------------------------------
                # OBROUND APERTURE
                # --------------------------------------------

                elif aperture_type == "Obround":

                    width = getattr(
                        aperture,
                        "width",
                        None
                    )

                    height = getattr(
                        aperture,
                        "height",
                        None
                    )

                    if width and height:

                        width = min(
                            width,
                            height
                        )

                # --------------------------------------------
                # SAVE WIDTH
                # --------------------------------------------

                if width is not None:

                    try:

                        width = float(width)

                        if width > 0:

                            widths.append(
                                round(width, 4)
                            )

                    except Exception:

                        pass


        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        if widths:

            result[
                "minimum_trace_width"
            ] = round(
                min(widths),
                4
            )

            result[
                "trace_count"
            ] = len(widths)

            result[
                "widths"
            ] = sorted(
                list(set(widths))
            )

        result[
            "success"
        ] = True

    except Exception as e:

        result[
            "errors"
        ].append(
            str(e)
        )

    return result
    
# ============================================================
# COPPER SPACING ANALYSIS
# ============================================================

def analyze_copper_spacing(file_path):

    result = {
        "success": False,
        "minimum_spacing": None,
        "comparisons": 0,
        "errors": []
    }

    try:

        import gerber
        import math

        layer = gerber.read(file_path)

        primitives = []

        # ----------------------------------------------------
        # COLLECT LINE / ARC GEOMETRY
        # ----------------------------------------------------

        for primitive in layer.primitives:

            primitive_type = type(
                primitive
            ).__name__

            if primitive_type not in [
                "Line",
                "Arc"
            ]:
                continue

            aperture = getattr(
                primitive,
                "aperture",
                None
            )

            if aperture is None:
                continue

            width = None

            aperture_type = type(
                aperture
            ).__name__

            if aperture_type == "Circle":

                width = getattr(
                    aperture,
                    "diameter",
                    None
                )

            elif aperture_type == "Rectangle":

                width = getattr(
                    aperture,
                    "width",
                    None
                )

            elif aperture_type == "Obround":

                w = getattr(
                    aperture,
                    "width",
                    None
                )

                h = getattr(
                    aperture,
                    "height",
                    None
                )

                if w and h:

                    width = min(w, h)

            if width is None:

                continue

            try:

                width = float(width)

            except Exception:

                continue

            start = getattr(
                primitive,
                "start",
                None
            )

            end = getattr(
                primitive,
                "end",
                None
            )

            if start is None or end is None:

                continue

            primitives.append({

                "type": primitive_type,

                "start": start,

                "end": end,

                "width": width

            })


        # ----------------------------------------------------
        # DISTANCE BETWEEN TWO LINE SEGMENTS
        # ----------------------------------------------------

        def point_to_segment_distance(
            px,
            py,
            ax,
            ay,
            bx,
            by
        ):

            dx = bx - ax
            dy = by - ay

            if dx == 0 and dy == 0:

                return math.hypot(
                    px - ax,
                    py - ay
                )

            t = (

                (px - ax) * dx +
                (py - ay) * dy

            ) / (

                dx * dx +
                dy * dy

            )

            t = max(
                0,
                min(
                    1,
                    t
                )
            )

            closest_x = ax + t * dx
            closest_y = ay + t * dy

            return math.hypot(

                px - closest_x,

                py - closest_y

            )


        # ----------------------------------------------------
        # CALCULATE SPACING
        # ----------------------------------------------------

        minimum_spacing = None

        comparisons = 0

        for i in range(
            len(primitives)
        ):

            p1 = primitives[i]

            for j in range(
                i + 1,
                len(primitives)
            ):

                p2 = primitives[j]
                # ------------------------------------------------
                # SKIP PRIMITIVES THAT ARE DIRECTLY CONNECTED
                # ------------------------------------------------

                tolerance = 0.001

                def points_equal(p1, p2):

                    return (

                        abs(p1[0] - p2[0]) <= tolerance

                        and

                        abs(p1[1] - p2[1]) <= tolerance

                    )


                if (

                    points_equal(
                        p1["start"],
                        p2["start"]
                    )

                    or

                    points_equal(
                        p1["start"],
                        p2["end"]
                    )

                    or

                    points_equal(
                        p1["end"],
                        p2["start"]
                    )

                    or

                    points_equal(
                        p1["end"],
                        p2["end"]
                    )

                ):

                    continue
                comparisons += 1

                # --------------------------------------------
                # TEMPORARY CENTERLINE DISTANCE
                # --------------------------------------------

                distances = [

                    point_to_segment_distance(

                        p1["start"][0],
                        p1["start"][1],

                        p2["start"][0],
                        p2["start"][1],

                        p2["end"][0],
                        p2["end"][1]

                    ),

                    point_to_segment_distance(

                        p1["end"][0],
                        p1["end"][1],

                        p2["start"][0],
                        p2["start"][1],

                        p2["end"][0],
                        p2["end"][1]

                    ),

                    point_to_segment_distance(

                        p2["start"][0],
                        p2["start"][1],

                        p1["start"][0],
                        p1["start"][1],

                        p1["end"][0],
                        p1["end"][1]

                    ),

                    point_to_segment_distance(

                        p2["end"][0],
                        p2["end"][1],

                        p1["start"][0],
                        p1["start"][1],

                        p1["end"][0],
                        p1["end"][1]

                    )

                ]

                center_distance = min(
                    distances
                )

                # --------------------------------------------
                # SUBTRACT COPPER WIDTHS
                # --------------------------------------------

                copper_spacing = (

                    center_distance

                    - (

                        p1["width"] / 2

                        +

                        p2["width"] / 2

                    )

                )

                # Ignore overlapping/connected primitives
                if copper_spacing <= 0:

                    continue

                if (

                    minimum_spacing is None

                    or

                    copper_spacing < minimum_spacing

                ):

                    minimum_spacing = copper_spacing


        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        result[
            "minimum_spacing"
        ] = (

            round(
                minimum_spacing,
                4
            )

            if minimum_spacing is not None

            else None

        )

        result[
            "comparisons"
        ] = comparisons

        result[
            "success"
        ] = True


    except Exception as e:

        result[
            "errors"
        ].append(
            str(e)
        )

    return result
# ============================================================
# ANALYZE ALL COPPER LAYERS
# ============================================================

# ============================================================
# ANALYZE ALL COPPER LAYERS
# ============================================================

def analyze_project_copper(extracted_path, project_files):

    result = {
        "layers_analyzed": 0,
        "minimum_trace_width": None,
        "minimum_spacing": None,
        "total_traces": 0,
        "layers": []
    }

    all_widths = []
    all_spacings = []

    for item in project_files:

        if item.get("layer") not in [
            "Top Copper",
            "Bottom Copper"
        ]:
            continue

        filename = item["filename"]

        file_path = extracted_path / filename

        if not file_path.exists():
            continue

        # Analyze copper trace geometry
        analysis = analyze_copper_geometry(
            file_path
        )

        # Analyze copper spacing
        spacing_analysis = analyze_copper_spacing(
            file_path
        )

        # Store layer result
        layer_result = {
            "filename": filename,
            "layer": item["layer"],
            "analysis": analysis,
            "spacing_analysis": spacing_analysis
        }

        result["layers"].append(
            layer_result
        )

        # Trace width results
        if analysis.get("success"):

            result["layers_analyzed"] += 1

            result["total_traces"] += (
                analysis.get(
                    "trace_count",
                    0
                )
            )

            widths = analysis.get(
                "widths",
                []
            )

            all_widths.extend(
                widths
            )

        # Copper spacing results
        if spacing_analysis.get("success"):

            spacing = spacing_analysis.get(
                "minimum_spacing"
            )

            if spacing is not None:
                all_spacings.append(
                    spacing
                )

    # --------------------------------------------------------
    # MINIMUM TRACE WIDTH
    # --------------------------------------------------------

    if all_widths:

        result["minimum_trace_width"] = round(
            min(all_widths),
            4
        )

    # --------------------------------------------------------
    # MINIMUM COPPER SPACING
    # --------------------------------------------------------

    if all_spacings:

        result["minimum_spacing"] = round(
            min(all_spacings),
            4
        )

    return result
    
@app.post("/api/analyze")
async def analyze_pcb(

    file: UploadFile = File(...)

):

    # --------------------------------------------------------
    # VALIDATE FILE
    # --------------------------------------------------------

    if not file.filename:

        raise HTTPException(

            status_code=400,

            detail="No file uploaded."

        )

    # --------------------------------------------------------
    # PROJECT ID
    # --------------------------------------------------------

    project_id = str(
        uuid.uuid4()
    )

    # --------------------------------------------------------
    # FILE EXTENSION
    # --------------------------------------------------------

    file_extension = (
        get_file_extension(
            file.filename
        )
    )

    # --------------------------------------------------------
    # CREATE PROJECT DIRECTORY
    # --------------------------------------------------------

    project_path = (

        PROJECT_DIR

        / project_id

    )

    project_path.mkdir(

        parents=True,

        exist_ok=True

    )

    # --------------------------------------------------------
    # SAVE ORIGINAL FILE
    # --------------------------------------------------------

    original_filename = (
        safe_filename(
            file.filename
        )
    )

    uploaded_file_path = (

        project_path

        / original_filename

    )

    with open(

        uploaded_file_path,

        "wb"

    ) as buffer:

        shutil.copyfileobj(

            file.file,

            buffer

        )

    # --------------------------------------------------------
    # EXTRACTION DIRECTORY
    # --------------------------------------------------------

    extracted_path = (

        project_path

        / "extracted"

    )

    extracted_path.mkdir(

        exist_ok=True

    )

    # --------------------------------------------------------
    # EXTRACT / COPY FILE
    # --------------------------------------------------------

    try:

        if file_extension in {

            ".zip",
            ".tar",
            ".gz",
            ".tgz"

        }:

            extract_archive(

                uploaded_file_path,

                extracted_path

            )

        else:

            shutil.copy(

                uploaded_file_path,

                extracted_path

                / original_filename

            )

    except Exception as e:

        raise HTTPException(

            status_code=400,

            detail=(

                "Unable to process uploaded file: "

                f"{str(e)}"

            )

        )

    # --------------------------------------------------------
    # GET PROJECT FILES
    # --------------------------------------------------------

    project_files = (
        get_project_files(
            extracted_path
        )
    )
    
    if not project_files:

        raise HTTPException(

            status_code=400,

            detail=(
                "No valid files found "
                "inside uploaded archive."
            )

        )

    # --------------------------------------------------------
    # PCB 2D / 3D PREVIEW GENERATION
    # --------------------------------------------------------
    # This is the primary preview renderer. It uses the dedicated
    # pcb_renderer.py implementation and writes both preview files
    # into <project>/renders/.

    render_result = {
        "success": False,
        "renders": [],
        "error": None
    }

    if generate_pcb_previews is None:

        render_result["error"] = (
            "pcb_renderer could not be imported: "
            + str(PCB_RENDERER_IMPORT_ERROR)
        )

        print(
            "PCB preview renderer unavailable:",
            PCB_RENDERER_IMPORT_ERROR
        )

    else:

        try:

            render_result = generate_pcb_previews(
                project_path,
                extracted_path,
                project_files
            )

            if not isinstance(render_result, dict):

                render_result = {
                    "success": False,
                    "renders": [],
                    "error": (
                        "pcb_renderer returned an invalid result."
                    )
                }

        except Exception as e:

            print(
                "PCB preview generation error:",
                str(e)
            )

            render_result = {
                "success": False,
                "renders": [],
                "error": str(e)
            }

    # --------------------------------------------------------
    # PREVIEW URLS
    # --------------------------------------------------------

    preview_2d = None
    preview_3d = None

    preview_items = render_result.get(
        "renders",
        []
    ) if isinstance(render_result, dict) else []

    if isinstance(preview_items, list):

        for preview in preview_items:

            if not isinstance(preview, dict):
                continue

            name = str(
                preview.get("name", "")
            ).lower()

            path = (
                preview.get("path")
                or preview.get("image")
            )

            if not path:
                continue

            if "2d" in name and preview_2d is None:
                preview_2d = path

            if "3d" in name and preview_3d is None:
                preview_3d = path

    # The renderer uses these fixed filenames. Use them as a fallback
    # when the renderer succeeded but did not return explicit entries.
    render_dir = (
        project_path
        / "renders"
    )

    if preview_2d is None:

        candidate_2d = (
            render_dir
            / "pcb_2d_preview.png"
        )

        if candidate_2d.exists():
            preview_2d = (
                f"/projects/{project_id}/renders/"
                "pcb_2d_preview.png"
            )

    if preview_3d is None:

        candidate_3d = (
            render_dir
            / "pcb_3d_preview.png"
        )

        if candidate_3d.exists():
            preview_3d = (
                f"/projects/{project_id}/renders/"
                "pcb_3d_preview.png"
            )

    preview_front = (
        f"/projects/{project_id}/renders/pcb_top_2d.png"
        if (render_dir / "pcb_top_2d.png").exists()
        else (
            preview_2d
            or (
                f"/projects/{project_id}/renders/pcb_2d_preview.png"
                if (render_dir / "pcb_2d_preview.png").exists()
                else None
            )
        )
    )

    preview_back = (
        f"/projects/{project_id}/renders/pcb_bottom_2d.png"
        if (render_dir / "pcb_bottom_2d.png").exists()
        else None
    )

    preview_front_3d = (
        f"/projects/{project_id}/renders/pcb_top_3d.png"
        if (render_dir / "pcb_top_3d.png").exists()
        else (
            preview_3d
            or (
                f"/projects/{project_id}/renders/pcb_3d_preview.png"
                if (render_dir / "pcb_3d_preview.png").exists()
                else None
            )
        )
    )

    preview_back_3d = (
        f"/projects/{project_id}/renders/pcb_bottom_3d.png"
        if (render_dir / "pcb_bottom_3d.png").exists()
        else None
    )

    # --------------------------------------------------------
    # PCB SUMMARY
    # --------------------------------------------------------

    pcb_summary = (
        build_pcb_summary(
            project_files
        )
    )

    # --------------------------------------------------------
    # DRILL ANALYSIS
    # --------------------------------------------------------

    drill_analysis = (
        analyze_project_drills(
            extracted_path
        )
    )

    # --------------------------------------------------------
    # BOARD ANALYSIS
    # --------------------------------------------------------

    board_analysis = (
        analyze_project_board(
            extracted_path
        )
    )
    
    # --------------------------------------------------------
    # COPPER GEOMETRY ANALYSIS
    # --------------------------------------------------------

    copper_analysis = analyze_project_copper(
        extracted_path,
        project_files
    )

    # --------------------------------------------------------
    # UPDATE SUMMARY
    # --------------------------------------------------------

    if board_analysis.get(
        "outline_found"
    ):

        pcb_summary[
            "board_outline_found"
        ] = True

    # --------------------------------------------------------
    # LAYER STACK
    # --------------------------------------------------------

    layer_stack = (
        build_layer_stack(
            project_files
        )
    )

    # --------------------------------------------------------
    # DFM CHECKS
    # --------------------------------------------------------

    dfm_analysis = run_dfm_checks(
        pcb_summary,
        drill_analysis,
        board_analysis,
        copper_analysis
    )

    # --------------------------------------------------------
    # LEGACY PER-LAYER 2D RENDERS
    # --------------------------------------------------------
    # Keep the per-layer renderer for the Layers view. The primary
    # 2D/3D previews are generated by pcb_renderer.py above.

    try:

        renders = render_gerber_layers(
            extracted_path,
            project_id
        )

    except Exception as render_error:

        print(
            "Per-layer render error:",
            render_error
        )

        renders = {
            "total_renders": 0,
            "layers": []
        }

    # --------------------------------------------------------
    # WEBSITE DISPLAY DATA
    # --------------------------------------------------------

    board_display = None

    if board_analysis.get(
        "outline_found"
    ):

        dimensions = (
            board_analysis.get(
                "dimensions"
            )
        )

        if dimensions:

            board_display = {

                "width_mm":

                    round(

                        dimensions[
                            "width_mm"
                        ],

                        2

                    ),

                "height_mm":

                    round(

                        dimensions[
                            "height_mm"
                        ],

                        2

                    ),

                "display":

                    f"{dimensions['width_mm']:.2f} "
                    f"× "
                    f"{dimensions['height_mm']:.2f} mm"

            }

    # --------------------------------------------------------
    # RETURN RESULT
    # --------------------------------------------------------

    return {

        "project_id":
            project_id,

        "filename":
            original_filename,

        "file_type":
            file_extension,

        "pcb_summary":
            pcb_summary,

                "board_size":
            board_display,

        # ----------------------------------------------------
        # DASHBOARD SUMMARY VALUES
        # ----------------------------------------------------

        "board_width":
            (
                board_display["width_mm"]
                if board_display
                else None
            ),

        "board_height":
            (
                board_display["height_mm"]
                if board_display
                else None
            ),

        "layer_count":
            max(2, pcb_summary.get("copper_layers", 2)),

        "drill_hits":
            drill_analysis.get(
                "total_drill_hits",
                0
            ),

        "drill_analysis":
            drill_analysis,

        "board_analysis":
            board_analysis,
            
        "copper_analysis": 
            copper_analysis,

        "layer_stack":
            layer_stack,

        "dfm_analysis":
            dfm_analysis,

        "renders":
            renders,

        "pcb_previews":
            render_result,

        "preview_2d":
            preview_2d,

        "preview_3d":
            preview_3d,

        "preview_front":
            preview_front,

        "preview_back":
            preview_back,

        "preview_front_3d":
            preview_front_3d,

        "preview_back_3d":
            preview_back_3d,

        "total_files":
            len(project_files),

        "files":

            [

                {

                    "filename":
                        item["filename"],

                    "category":
                        item["category"],

                    "layer":
                        item["layer"]

                }

                for item
                in project_files

            ]

    }


# ============================================================
# GERBER VECTOR VIEWER API
# ============================================================

@app.get("/api/project/{project_id}/viewer")
def get_gerber_viewer(project_id: str):

    project_path = PROJECT_DIR / project_id

    if not project_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Project not found."
        )

    extracted_path = project_path / "extracted"

    if not extracted_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Extracted Gerber files not found."
        )

    project_files = get_project_files(
        extracted_path
    )

    # Reuse the exact board-outline analysis that powers the Analysis Result.
    # The viewer must not independently choose its viewport from arbitrary
    # Gerber extents (drawings/frames can be larger than the PCB).
    board_analysis = analyze_project_board(
        extracted_path
    )

    viewer_data = build_viewer_data(
        extracted_path,
        project_files,
        board_analysis=board_analysis
    )

    return {
        "success": True,
        "project_id": project_id,
        "viewer": viewer_data
    }

