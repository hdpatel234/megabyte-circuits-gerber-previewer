"""
PCB GLOBAL LAYER / FILE CLASSIFIER V10
======================================

Goal:
    Recognize common PCB fabrication/assembly layer names across major
    EDA/CAM ecosystems without assuming one CAD vendor's naming convention.

Design:
    1) File content / Gerber X2 attributes
    2) Explicit extension convention
    3) Filename semantics
    4) Conservative fallback

Important:
    .GBR/.GER/.PHO/.ART are generic Gerber containers. The extension alone
    cannot tell the physical layer. Gerber X2 .FileFunction, when present,
    is the strongest source of layer identity.

This module is intentionally independent of main.py and gerber_viewer.py.
Import classify_file() from both places so classification stays identical.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# FILE EXTENSIONS
# ---------------------------------------------------------------------------

# Generic Gerber containers. These can represent ANY image layer.
GENERIC_GERBER_EXTENSIONS = {
    ".gbr", ".ger", ".gerber", ".pho", ".ph", ".art",
    ".cmp", ".sol", ".top", ".bot",
}

# Conventional Gerber layer extensions.
GERBER_EXTENSIONS = GENERIC_GERBER_EXTENSIONS | {
    # copper / mask / silk / paste
    ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gtp", ".gbp",
    # Altium / Protel inner & mechanical families
    *{f".g{i}" for i in range(1, 100)},
    *{f".gp{i}" for i in range(1, 100)},
    *{f".gm{i}" for i in range(1, 100)},
    *{f".gd{i}" for i in range(1, 100)},
    *{f".gg{i}" for i in range(1, 100)},
    *{f".gl{i}" for i in range(1, 100)},
    # Altium common
    ".gko", ".gml", ".gmd", ".gpt", ".gpb",
    # older / alternate
    ".plc", ".pls", ".stc", ".sts",
    ".psm", ".pss", ".smt", ".smb", ".smp",
    ".sst", ".ssb",
    ".psp", ".psp1", ".psp2",
    # Circuit / CAD artwork conventions
    ".art1", ".art2", ".art3", ".art4", ".art5", ".art6",
    ".art7", ".art8", ".art9", ".art10",
    # miscellaneous CAM image names
    ".otl", ".oln",
}

# Actual NC / Excellon-style drill containers.
DRILL_EXTENSIONS = {
    ".drl", ".xln", ".exc", ".tap", ".ncd", ".nc", ".rou",
    ".drd", ".drill", ".drillfile", ".xnc",
}

# Common archive containers (never Gerber or Excellon).
ARCHIVE_EXTENSIONS = {
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".cab", ".iso",
}

# Explicit non-CAM support / document / mechanical drawings and report files.
NON_CAM_EXTENSIONS = {
    ".pdf", ".drr", ".rep", ".extrep", ".apr", ".apt", ".ldp", ".rul",
    ".bom", ".csv", ".xls", ".xlsx", ".xlsm",
    ".pos", ".pnp", ".xy", ".cen", ".centroid",
    ".step", ".stp", ".iges", ".igs", ".dxf", ".dwg",
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".svg",
    ".doc", ".docx", ".rtf", ".odt",
    ".gbrjob", ".job", ".json", ".xml", ".cvg",
    ".stackup", ".stack", ".stk",
}

# Common manufacturing/support/document files.
SUPPORT_EXTENSIONS = ARCHIVE_EXTENSIONS | NON_CAM_EXTENSIONS | {
    ".ipc", ".ipc356", ".d356", ".net", ".netlist", ".txt",
}


# ---------------------------------------------------------------------------
# STANDARD EXTENSION MAP
# ---------------------------------------------------------------------------

EXTENSION_LAYER_MAP: Dict[str, str] = {
    # Altium / Protel standard
    ".gtl": "Top Copper",
    ".gbl": "Bottom Copper",
    ".gts": "Top Solder Mask",
    ".gbs": "Bottom Solder Mask",
    ".gto": "Top Silkscreen",
    ".gbo": "Bottom Silkscreen",
    ".gtp": "Top Paste",
    ".gbp": "Bottom Paste",
    ".gko": "Board Profile",
    ".gml": "Board Profile",
    ".gmd": "Board Profile",

    # Common alternative extension conventions
    ".cmp": "Top Copper",
    ".sol": "Bottom Copper",
    ".stc": "Top Solder Mask",
    ".sts": "Bottom Solder Mask",
    ".plc": "Top Silkscreen",
    ".pls": "Bottom Silkscreen",
    ".top": "Top Copper",
    ".bot": "Bottom Copper",

    # Some commonly encountered mask/paste abbreviations
    ".smt": "Top Solder Mask",
    ".smb": "Bottom Solder Mask",
    ".smp": "Top Solder Mask",
    ".psm": "Top Solder Mask",
    ".pss": "Top Silkscreen",
    ".sst": "Top Silkscreen",
    ".ssb": "Bottom Silkscreen",
}

# Extensions where the physical meaning is family-level or sequence-based.
EXTENSION_FAMILY_MAP: Dict[str, str] = {
    **{f".gd{i}": "Drill Drawing" for i in range(1, 100)},
    **{f".gg{i}": "Drill Guide" for i in range(1, 100)},
    **{f".gm{i}": "Mechanical / Profile" for i in range(1, 100)},
    **{f".gp{i}": "Pad / Paste / Plane (name required)" for i in range(1, 100)},
}


# ---------------------------------------------------------------------------
# NORMALIZATION
# ---------------------------------------------------------------------------

def normalize_name(value: str) -> str:
    s = str(value or "").strip().lower()
    s = s.replace("\\", "/").split("/")[-1]
    return s


def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_name(value))


def side_from_name(value: str) -> Optional[str]:
    n = normalize_name(value)
    c = compact(n)

    top_tokens = (
        "top", "upper", "front", "frontside",
        "f.cu", "f_mask", "f.mask", "f_silks", "f.silks",
        "f_paste", "f.paste", "f_adhes", "f.adhes",
        "f_fab", "f.fab",
    )
    bot_tokens = (
        "bottom", "bot", "lower", "back", "backside",
        "b.cu", "b_mask", "b.mask", "b_silks", "b.silks",
        "b_paste", "b.paste", "b_adhes", "b.adhes",
        "b_fab", "b.fab",
    )

    top = any(x in n for x in top_tokens) or any(
        x in c for x in ("top", "upper", "front")
    )
    bottom = any(x in n for x in bot_tokens) or any(
        x in c for x in ("bottom", "bot", "lower", "back")
    )

    if top and not bottom:
        return "top"
    if bottom and not top:
        return "bottom"
    return None


def inner_number(filename: str) -> Optional[int]:
    n = normalize_name(filename)
    ext = Path(filename).suffix.lower()

    # Altium G1, G2 ... convention.
    m = re.fullmatch(r"\.g(\d+)", ext)
    if m:
        return int(m.group(1))

    patterns = (
        r"(?:^|[_\-. ])in[_\-. ]*(\d+)(?:[_\-. ]*cu)?(?:$|[_\-. ])",
        r"(?:^|[_\-. ])inner[_\-. ]*(?:copper[_\-. ]*)?(\d+)",
        r"(?:^|[_\-. ])inner[_\-. ]*layer[_\-. ]*(\d+)",
        r"(?:^|[_\-. ])internal[_\-. ]*(?:copper[_\-. ]*)?(\d+)",
        r"(?:^|[_\-. ])mid[_\-. ]*(?:layer[_\-. ]*)?(\d+)",
        r"(?:^|[_\-. ])layer[_\-. ]*(\d+)",
        r"(?:^|[_\-. ])l(\d+)(?:[_\-. ]*cu)?(?:$|[_\-. ])",
    )
    for p in patterns:
        m = re.search(p, n)
        if m:
            try:
                value = int(m.group(1))
                if value > 0:
                    return value
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# GERBER X2 / X3 FILE FUNCTION
# ---------------------------------------------------------------------------

def gerber_x2_attributes(text: str) -> Dict[str, str]:
    if isinstance(text, (list, tuple)):
        text = "\n".join(text)
    text = str(text or "")
    result: Dict[str, str] = {}

    patterns = [
        r"%TF\.([A-Za-z0-9_.]+),([^%*]+)\*%",
        r"G04\s+#@!\s*TF\.([A-Za-z0-9_.]+),([^*]+)\*",
        r"G04\s+#@!\s*\.?([A-Za-z0-9_.]+),([^*]+)\*",
    ]

    for pattern in patterns:
        for m in re.finditer(pattern, text, flags=re.I):
            key = m.group(1).strip().lower()
            value = m.group(2).strip()
            result[key] = value

    return result


def classify_gerber_x2(text: str) -> Optional[str]:
    attrs = gerber_x2_attributes(text)
    ff = attrs.get("filefunction", "")
    if not ff:
        return None

    fields = [x.strip() for x in ff.split(",")]
    if not fields:
        return None

    function = fields[0].lower()
    low = ff.lower()

    # Copper,L<p>,Top/Inr/Bot[,Plane|Signal|Mixed|Hatched]
    if function == "copper":
        layer_num = None
        side = None

        for field in fields[1:]:
            if re.fullmatch(r"l\d+", field, re.I):
                layer_num = int(field[1:])
            elif field.lower() in {"top", "bot", "bottom", "inr", "inner"}:
                side = field.lower()

        if side == "top" or layer_num == 1 and side is None:
            return "Top Copper"
        if side in {"bot", "bottom"}:
            return "Bottom Copper"
        if layer_num is not None:
            return f"Inner Copper {layer_num}"
        return "Copper"

    if function == "soldermask":
        if "top" in low:
            return "Top Solder Mask"
        if "bot" in low or "bottom" in low:
            return "Bottom Solder Mask"
        return "Solder Mask"

    if function == "legend":
        if "top" in low:
            return "Top Silkscreen"
        if "bot" in low or "bottom" in low:
            return "Bottom Silkscreen"
        return "Silkscreen"

    if function == "paste":
        if "top" in low:
            return "Top Paste"
        if "bot" in low or "bottom" in low:
            return "Bottom Paste"
        return "Paste"

    if function == "glue":
        if "top" in low:
            return "Top Adhesive"
        if "bot" in low or "bottom" in low:
            return "Bottom Adhesive"
        return "Adhesive"

    if function == "profile":
        return "Board Profile"

    if function == "plated":
        if "blind" in low:
            return "Blind Via Drill"
        if "buried" in low:
            return "Buried Via Drill"
        if "pth" in low:
            return "PTH Drill"
        return "PTH Drill"

    if function == "nonplated":
        if "blind" in low:
            return "Blind Via Drill"
        if "buried" in low:
            return "Buried Via Drill"
        return "NPTH Drill"

    if function == "drillmap":
        return "Drill Drawing"

    if function == "fabricationdrawing":
        return "Fabrication Drawing"

    if function == "vcutmap":
        return "V-Score Drawing"

    if function == "vcut":
        return "V-Score"

    if function == "depthrout":
        return "Depth Routing"

    if function == "viafill":
        return "Via Fill"

    if function == "assemblydrawing":
        if "top" in low:
            return "Top Assembly Drawing"
        if "bot" in low or "bottom" in low:
            return "Bottom Assembly Drawing"
        return "Assembly Drawing"

    if function == "arraydrawing":
        return "Array Drawing"

    if function == "component":
        if "top" in low:
            return "Top Component"
        if "bot" in low or "bottom" in low:
            return "Bottom Component"
        return "Component"

    if function == "pads":
        if "top" in low:
            return "Top Pads"
        if "bot" in low or "bottom" in low:
            return "Bottom Pads"
        return "Pads"

    if function == "carbonmask":
        return "Top Carbon Mask" if "top" in low else "Bottom Carbon Mask" if "bot" in low else "Carbon Mask"

    if function == "goldmask":
        return "Top Gold Mask" if "top" in low else "Bottom Gold Mask" if "bot" in low else "Gold Mask"

    if function == "heatsinkmask":
        return "Top Heatsink Mask" if "top" in low else "Bottom Heatsink Mask" if "bot" in low else "Heatsink Mask"

    if function == "peelablemask":
        return "Top Peelable Mask" if "top" in low else "Bottom Peelable Mask" if "bot" in low else "Peelable Mask"

    if function == "silvermask":
        return "Top Silver Mask" if "top" in low else "Bottom Silver Mask" if "bot" in low else "Silver Mask"

    if function == "tinmask":
        return "Top Tin Mask" if "top" in low else "Bottom Tin Mask" if "bot" in low else "Tin Mask"

    if function == "drawing":
        if "stackup" in low:
            return "Stackup Drawing"
        return "Drawing"

    if function == "otherdrawing":
        return "Other Drawing"

    if function == "other":
        return "Other Gerber"

    return None


# ---------------------------------------------------------------------------
# FILENAME SEMANTICS
# ---------------------------------------------------------------------------

RULES = [
    # Most specific first.
    ("Board Profile", (
        "edge.cuts", "edge_cuts", "edge-cut", "edgecut",
        "board_outline", "boardoutline", "board_profile",
        "boardprofile", "pcb_profile", "pcbprofile",
        "profile", "outline", "contour", "board_edge", "boardedge",
    )),
    ("Top Copper", (
        "copper_signal_top", "copper_top", "top_copper", "topcopper",
        "toplayer", "top_layer", "front_copper",
        "signal_top", "signal_front", "f.cu", "f_cu", "f-cu",
        "frontcu", "front_copper",
    )),
    ("Bottom Copper", (
        "copper_signal_bot", "copper_signal_bottom",
        "copper_bottom", "copper_bot", "bottom_copper",
        "bottomcopper", "bottomlayer", "bottom_layer",
        "back_copper", "signal_bottom", "signal_bot",
        "signal_back", "b.cu", "b_cu", "b-cu", "backcu",
    )),
    ("Top Solder Mask", (
        "soldermask_top", "solder_mask_top", "topsoldermask",
        "top_soldermask", "top_solder_mask", "topmask",
        "top_mask", "mask_top", "masktop", "solder_top",
        "f.mask", "f_mask", "fmask",
    )),
    ("Bottom Solder Mask", (
        "soldermask_bottom", "soldermask_bot",
        "solder_mask_bottom", "solder_mask_bot",
        "bottomsoldermask", "bottom_soldermask",
        "bottom_solder_mask", "bottommask", "bottom_mask",
        "mask_bottom", "maskbottom", "solder_bottom",
        "solder_bot", "b.mask", "b_mask", "bmask",
    )),
    ("Top Silkscreen", (
        "silkscreen_top", "top_silkscreen", "topsilkscreen",
        "top_silk", "topsilk", "legend_top", "legendtop",
        "top_legend", "toplegend", "top_overlay", "topoverlay",
        "silk_top", "silktop", "f.silks", "f_silks",
        "f.silkscreen", "f_silkscreen",
    )),
    ("Bottom Silkscreen", (
        "silkscreen_bottom", "bottom_silkscreen",
        "bottomsilkscreen", "bottom_silk", "bottomsilk",
        "legend_bottom", "legendbottom", "bottom_legend",
        "bottomlegend", "bottom_overlay", "bottomoverlay",
        "silk_bottom", "silkbottom", "b.silks", "b_silks",
        "b.silkscreen", "b_silkscreen",
    )),
    ("Top Paste", (
        "paste_top", "top_paste", "toppaste",
        "solderpaste_top", "top_solderpaste", "top_solder_paste",
        "top_stencil", "topstencil", "top_cream", "topcream",
        "f.paste", "f_paste", "f.paste",
    )),
    ("Bottom Paste", (
        "paste_bottom", "paste_bot", "bottom_paste",
        "bottompaste", "solderpaste_bottom", "bottom_solderpaste",
        "bottom_solder_paste", "bottom_stencil", "bottomstencil",
        "bottom_cream", "bottomcream", "b.paste", "b_paste",
    )),
    ("Top Adhesive", (
        "adhesive_top", "top_adhesive", "topadhesive",
        "glue_top", "top_glue", "f.adhes", "f_adhes",
    )),
    ("Bottom Adhesive", (
        "adhesive_bottom", "bottom_adhesive", "bottomadhesive",
        "glue_bottom", "bottom_glue", "b.adhes", "b_adhes",
    )),
    ("Drill Drawing", (
        "drillmap", "drill_map", "drilldrawing", "drill_drawing",
        "drill_guide", "drillguide",
    )),
    ("V-Score", (
        "vscore", "v-score", "v_score", "vcut", "v-cut", "v_cut",
        "scoring", "score_lines",
    )),
    ("Mechanical / Routing", (
        "milling", "mill", "routing_layer", "route_layer",
        "routing", "route", "slots", "slot", "cutout", "cut_out",
        "cut-out", "mechanical",
    )),
    ("Keep Out", (
        "keepout", "keep_out", "keep-out", "keepoutlayer",
        "keep_out_layer", "restricted",
    )),
    ("Top Carbon Mask", (
        "carbon_top", "carbonmask_top", "top_carbon",
        "topcarbon", "carbon_top_mask",
    )),
    ("Bottom Carbon Mask", (
        "carbon_bottom", "carbon_bot", "carbonmask_bottom",
        "bottom_carbon", "bottomcarbon",
    )),
    ("Top Coverlay", ("coverlay_top", "top_coverlay", "topcoverlay")),
    ("Bottom Coverlay", ("coverlay_bottom", "coverlay_bot", "bottom_coverlay", "bottomcoverlay")),
    ("Top Stiffener", ("stiffener_top", "top_stiffener", "topstiffener")),
    ("Bottom Stiffener", ("stiffener_bottom", "stiffener_bot", "bottom_stiffener", "bottomstiffener")),
    ("Top Assembly", ("assembly_top", "top_assembly", "assemblytop", "assy_top", "topassy")),
    ("Bottom Assembly", ("assembly_bottom", "bottom_assembly", "assemblybottom", "assy_bottom", "bottomassy")),
    ("Top Component", ("component_top", "top_component", "componenttop")),
    ("Bottom Component", ("component_bottom", "bottom_component", "componentbottom")),
]


EXACT_STEM_MAP = {
    # Top Copper
    "top": "Top Copper",
    "toplayer": "Top Copper",
    "top_layer": "Top Copper",
    "topcopper": "Top Copper",
    "top_copper": "Top Copper",
    "gtl": "Top Copper",
    "cmp": "Top Copper",
    "art1": "Top Copper",
    "f_cu": "Top Copper",
    "f.cu": "Top Copper",
    "front": "Top Copper",
    "front_copper": "Top Copper",
    "top_signal": "Top Copper",
    "copper_top": "Top Copper",

    # Bottom Copper
    "bot": "Bottom Copper",
    "bottom": "Bottom Copper",
    "bottomlayer": "Bottom Copper",
    "bottom_layer": "Bottom Copper",
    "bottomcopper": "Bottom Copper",
    "bottom_copper": "Bottom Copper",
    "bot_copper": "Bottom Copper",
    "gbl": "Bottom Copper",
    "sol": "Bottom Copper",
    "art2": "Bottom Copper",
    "b_cu": "Bottom Copper",
    "b.cu": "Bottom Copper",
    "back": "Bottom Copper",
    "back_copper": "Bottom Copper",
    "bot_signal": "Bottom Copper",
    "copper_bot": "Bottom Copper",
    "copper_bottom": "Bottom Copper",

    # Inner Copper Layers
    "in1": "Inner Copper 1",
    "in2": "Inner Copper 2",
    "in3": "Inner Copper 3",
    "in4": "Inner Copper 4",
    "inner1": "Inner Copper 1",
    "inner2": "Inner Copper 2",
    "inner3": "Inner Copper 3",
    "inner4": "Inner Copper 4",
    "mid1": "Inner Copper 1",
    "mid2": "Inner Copper 2",
    "mid3": "Inner Copper 3",
    "mid4": "Inner Copper 4",
    "int1": "Inner Copper 1",
    "int2": "Inner Copper 2",
    "int3": "Inner Copper 3",
    "int4": "Inner Copper 4",

    # Top Solder Mask
    "smt": "Top Solder Mask",
    "sm_top": "Top Solder Mask",
    "sm_t": "Top Solder Mask",
    "mask_t": "Top Solder Mask",
    "mask_top": "Top Solder Mask",
    "masktop": "Top Solder Mask",
    "topmask": "Top Solder Mask",
    "top_mask": "Top Solder Mask",
    "top_sm": "Top Solder Mask",
    "tsm": "Top Solder Mask",
    "sm1": "Top Solder Mask",
    "soldermask_top": "Top Solder Mask",
    "solder_mask_top": "Top Solder Mask",
    "gts": "Top Solder Mask",
    "stc": "Top Solder Mask",
    "f_mask": "Top Solder Mask",
    "f.mask": "Top Solder Mask",
    "solder_top": "Top Solder Mask",
    "psm": "Top Solder Mask",
    "smp": "Top Solder Mask",

    # Bottom Solder Mask
    "smb": "Bottom Solder Mask",
    "sm_bot": "Bottom Solder Mask",
    "sm_b": "Bottom Solder Mask",
    "mask_b": "Bottom Solder Mask",
    "mask_bot": "Bottom Solder Mask",
    "maskbot": "Bottom Solder Mask",
    "botmask": "Bottom Solder Mask",
    "bottommask": "Bottom Solder Mask",
    "bot_mask": "Bottom Solder Mask",
    "bottom_mask": "Bottom Solder Mask",
    "bot_sm": "Bottom Solder Mask",
    "bsm": "Bottom Solder Mask",
    "sm2": "Bottom Solder Mask",
    "soldermask_bot": "Bottom Solder Mask",
    "soldermask_bottom": "Bottom Solder Mask",
    "solder_mask_bot": "Bottom Solder Mask",
    "solder_mask_bottom": "Bottom Solder Mask",
    "gbs": "Bottom Solder Mask",
    "sts": "Bottom Solder Mask",
    "b_mask": "Bottom Solder Mask",
    "b.mask": "Bottom Solder Mask",
    "solder_bot": "Bottom Solder Mask",
    "solder_bottom": "Bottom Solder Mask",
    "pss": "Bottom Solder Mask",

    # Top Silkscreen
    "sst": "Top Silkscreen",
    "ss_top": "Top Silkscreen",
    "ss_t": "Top Silkscreen",
    "silk_t": "Top Silkscreen",
    "silk_top": "Top Silkscreen",
    "silktop": "Top Silkscreen",
    "topsilk": "Top Silkscreen",
    "top_silk": "Top Silkscreen",
    "top_ss": "Top Silkscreen",
    "tss": "Top Silkscreen",
    "slk_t": "Top Silkscreen",
    "silkscreen_top": "Top Silkscreen",
    "top_silkscreen": "Top Silkscreen",
    "toplegend": "Top Silkscreen",
    "top_legend": "Top Silkscreen",
    "legendtop": "Top Silkscreen",
    "legend_top": "Top Silkscreen",
    "gto": "Top Silkscreen",
    "plc": "Top Silkscreen",
    "f_silks": "Top Silkscreen",
    "f.silks": "Top Silkscreen",
    "sto": "Top Silkscreen",

    # Bottom Silkscreen
    "ssb": "Bottom Silkscreen",
    "ss_bot": "Bottom Silkscreen",
    "ss_b": "Bottom Silkscreen",
    "silk_b": "Bottom Silkscreen",
    "silk_bot": "Bottom Silkscreen",
    "silkbot": "Bottom Silkscreen",
    "botsilk": "Bottom Silkscreen",
    "bottomsilk": "Bottom Silkscreen",
    "bot_silk": "Bottom Silkscreen",
    "bottom_silk": "Bottom Silkscreen",
    "bot_ss": "Bottom Silkscreen",
    "bss": "Bottom Silkscreen",
    "slk_b": "Bottom Silkscreen",
    "silkscreen_bot": "Bottom Silkscreen",
    "silkscreen_bottom": "Bottom Silkscreen",
    "legendbot": "Bottom Silkscreen",
    "legend_bot": "Bottom Silkscreen",
    "bottomlegend": "Bottom Silkscreen",
    "bottom_legend": "Bottom Silkscreen",
    "gbo": "Bottom Silkscreen",
    "pls": "Bottom Silkscreen",
    "b_silks": "Bottom Silkscreen",
    "b.silks": "Bottom Silkscreen",
    "sbo": "Bottom Silkscreen",

    # Top Paste
    "spt": "Top Paste",
    "sp_top": "Top Paste",
    "sp_t": "Top Paste",
    "paste_t": "Top Paste",
    "paste_top": "Top Paste",
    "pastetop": "Top Paste",
    "toppaste": "Top Paste",
    "top_paste": "Top Paste",
    "top_sp": "Top Paste",
    "tsp": "Top Paste",
    "pst_t": "Top Paste",
    "pst_top": "Top Paste",
    "solderpaste_top": "Top Paste",
    "top_stencil": "Top Paste",
    "gtp": "Top Paste",
    "f_paste": "Top Paste",
    "f.paste": "Top Paste",

    # Bottom Paste
    "spb": "Bottom Paste",
    "sp_bot": "Bottom Paste",
    "sp_b": "Bottom Paste",
    "paste_b": "Bottom Paste",
    "paste_bot": "Bottom Paste",
    "pastebot": "Bottom Paste",
    "botpaste": "Bottom Paste",
    "bottompaste": "Bottom Paste",
    "bot_paste": "Bottom Paste",
    "bottom_paste": "Bottom Paste",
    "bot_sp": "Bottom Paste",
    "bsp": "Bottom Paste",
    "pst_b": "Bottom Paste",
    "pst_bot": "Bottom Paste",
    "solderpaste_bot": "Bottom Paste",
    "bottom_stencil": "Bottom Paste",
    "gbp": "Bottom Paste",
    "b_paste": "Bottom Paste",
    "b.paste": "Bottom Paste",

    # Board Profile / Outline
    "bo": "Board Profile",
    "brd": "Board Profile",
    "profile": "Board Profile",
    "outline": "Board Profile",
    "board": "Board Profile",
    "edge_cuts": "Board Profile",
    "edgecuts": "Board Profile",
    "board_outline": "Board Profile",
    "board_profile": "Board Profile",
    "pcb_profile": "Board Profile",
    "pcb_outline": "Board Profile",
    "gko": "Board Profile",
    "gml": "Board Profile",
    "gmd": "Board Profile",
    "gm1": "Board Profile",

    # Drill
    "drill": "Drill",
    "drills": "Drill",
    "pth": "PTH Drill",
    "pth_drill": "PTH Drill",
    "pth_drl": "PTH Drill",
    "npth": "NPTH Drill",
    "npth_drill": "NPTH Drill",
    "npth_drl": "NPTH Drill",
    "org_drill": "Drill",
    "original_drill": "Drill",
    "drill_org": "Drill",
    "drill_original": "Drill",
    "drl_org": "Drill",
    "org_drl": "Drill",
    "drl": "Drill",
    "xln": "Drill",
    "tap": "Drill",
    "nc_drill": "Drill",
    "ncd": "Drill",
}


def classify_filename(filename: str) -> Optional[str]:
    stem = Path(filename).stem.lower()
    fname_lower = Path(filename).name.lower()

    if stem in EXACT_STEM_MAP:
        return EXACT_STEM_MAP[stem]
    if fname_lower in EXACT_STEM_MAP:
        return EXACT_STEM_MAP[fname_lower]

    name = normalize_name(filename)
    ext = Path(filename).suffix.lower()
    side = side_from_name(name)

    if ext in EXTENSION_LAYER_MAP:
        return EXTENSION_LAYER_MAP[ext]

    if ext in EXTENSION_FAMILY_MAP:
        family = EXTENSION_FAMILY_MAP[ext]
        if family.startswith("Drill"):
            return family
        # Continue semantic classification for GM/GP families.

    # Explicit inner copper before generic "layer" rules.
    n = inner_number(name)
    if n is not None:
        # G1/G2... are conventionally inner copper only when they are not
        # clearly a different family.
        if ext.startswith(".g") and not ext.startswith(".gp") and not ext.startswith(".gm"):
            return f"Inner Copper {n}"

    for label, tokens in RULES:
        if any(token in name for token in tokens):
            return label

    # Generic semantic families.
    if "silk" in name or "legend" in name or "overlay" in name:
        return "Bottom Silkscreen" if side == "bottom" else "Top Silkscreen"

    if "paste" in name or "stencil" in name or "cream" in name:
        return "Bottom Paste" if side == "bottom" else "Top Paste"

    if "adhes" in name or "glue" in name:
        return "Bottom Adhesive" if side == "bottom" else "Top Adhesive"

    if "soldermask" in name or "solder_mask" in name or "solderresist" in name:
        return "Bottom Solder Mask" if side == "bottom" else "Top Solder Mask"

    if "copper" in name or re.search(r"(?:^|[_\-.])cu(?:$|[_\-.])", name):
        if side == "bottom":
            return "Bottom Copper"
        if side == "top":
            return "Top Copper"

    if "plane" in name or "pour" in name:
        if any(x in name for x in ("ground", "gnd")):
            return "Ground Plane"
        if any(x in name for x in ("power", "pwr", "vcc", "vdd")):
            return "Power Plane"
        return "Copper Plane"

    if "assembly" in name or "assy" in name:
        return "Bottom Assembly" if side == "bottom" else "Top Assembly"

    if "courtyard" in name:
        return "Bottom Courtyard" if side == "bottom" else "Top Courtyard"

    if any(x in name for x in (
        "fabrication", "fab_drawing", "fabdrawing",
        "fab_note", "fabnote", "manufacturing",
        "dimension", "dimensions", "documentation", "document",
        "drawing", "notes"
    )):
        return "Documentation"

    if "shield" in name:
        return "Bottom Shield" if side == "bottom" else "Top Shield"

    if "foil" in name:
        return "Bottom Foil" if side == "bottom" else "Top Foil"

    if "dielectric" in name:
        return "Dielectric"

    if "prepreg" in name:
        return "Prepreg"

    if re.search(r"\bcore\b", name):
        return "Core"

    return None


# ---------------------------------------------------------------------------
# DRILL CLASSIFICATION
# ---------------------------------------------------------------------------

def classify_drill_filename(filename: str) -> str:
    n = normalize_name(filename)

    # NPTH must be before PTH.
    if any(x in n for x in (
        "npth", "nonplated", "non_plated", "non-plated",
        "nonplatedhole", "non_plated_hole"
    )):
        return "NPTH Drill"

    if any(x in n for x in (
        "blind_via", "blindvia", "blind_drill", "blind-drill"
    )):
        return "Blind Via Drill"

    if any(x in n for x in (
        "buried_via", "buriedvia", "buried_drill", "buried-drill"
    )):
        return "Buried Via Drill"

    if any(x in n for x in (
        "microvia", "micro_via", "micro-via",
        "laser_drill", "laserdrill", "laser-drill"
    )):
        return "Microvia / Laser Drill"

    if any(x in n for x in (
        "via_drill", "viadrill", "via_hole", "via-hole"
    )):
        return "Via Drill"

    if any(x in n for x in (
        "slot", "slots", "rout", "routing", "route"
    )):
        return "Routed / Slot Drill"

    if any(x in n for x in (
        "pth", "plated", "plated_hole", "plated-hole", "platedhole"
    )):
        return "PTH Drill"

    return "Drill"


# ---------------------------------------------------------------------------
# CONTENT TYPE DETECTION
# ---------------------------------------------------------------------------

def detect_file_type(filename: str, text: str = "") -> str:
    fname = str(getattr(filename, "name", filename))
    ext = Path(fname).suffix.lower()
    t = "\n".join(text) if isinstance(text, (list, tuple)) else str(text or "")
    if ext in {".drr", ".ldp", ".rep", ".extrep", ".rpt", ".apr", ".apt", ".rul"}:
        return "Support"
    if ext in DRILL_EXTENSIONS:
        return "Excellon"
    # Archives and non-CAM documents are always Support files.
    if ext in ARCHIVE_EXTENSIONS or (ext in NON_CAM_EXTENSIONS and "DRILL" not in fname.upper()):
        return "Support"

    # Binary files containing null bytes cannot be text-based Gerber or Excellon.
    if "\x00" in t:
        return "Support"

    # Gerber X2/X3 first.
    if "TF.FileFunction" in t or "%TF." in t or "#@! TF.FileFunction" in t:
        return "Gerber"

    # Strong Gerber syntax.
    if any(x in t for x in (
        "%FSL", "%FS", "%MO", "G04", "D01", "D02", "D03", "M02"
    )):
        if "%FS" in t or "D01" in t or "D02" in t or "D03" in t:
            return "Gerber"

    # Excellon / XNC indicators.
    if any(x in t.upper() for x in (
        "M48", "METRIC", "INCH", "FMAT,", "T01", "T02", "M30"
    )):
        if re.search(r"(?:^|\n)\s*T\d+", t, re.I) or "DRILL" in fname.upper():
            return "Excellon"

    if ext in DRILL_EXTENSIONS or "DRILL" in fname.upper():
        return "Excellon"

    if ext in GERBER_EXTENSIONS:
        return "Gerber"

    if ext in SUPPORT_EXTENSIONS and "DRILL" not in fname.upper():
        return "Support"

    # Generic text that looks like an IPC-2581 document.
    if "<IPC-2581" in t or "<ipc-2581" in t:
        return "IPC-2581"

    if "<odb" in t.lower() or "odb++" in t.lower():
        return "ODB++"

    # Filename stem fallback for files with non-standard or missing extension (e.g. 'top', 'bot', 'profile')
    inferred_layer = classify_filename(fname)
    if inferred_layer:
        if inferred_layer in {"Drill", "PTH Drill", "NPTH Drill", "Via Drill", "Blind Via Drill", "Buried Via Drill"} or "drill" in inferred_layer.lower():
            return "Excellon"
        return "Gerber"

    return "Unknown"


# ---------------------------------------------------------------------------
# MASTER CLASSIFIER
# ---------------------------------------------------------------------------

def classify_file(
    filename: str,
    text: str = "",
    supplied_layer: str = "",
) -> Dict[str, Any]:
    """
    Return one consistent classification record.

    confidence:
        100 = explicit Gerber X2 FileFunction
        95+ = unambiguous standard extension
        90+ = very strong descriptive filename
        70-89 = semantic inference
        <70 = weak / unknown
    """
    file_type = detect_file_type(filename, text)
    ext = Path(filename).suffix.lower()
    x2_layer = classify_gerber_x2(text) if file_type == "Gerber" else None

    if x2_layer:
        is_drill_layer = x2_layer in {"Drill", "PTH Drill", "NPTH Drill", "Via Drill", "Blind Via Drill", "Buried Via Drill"} or "drill" in x2_layer.lower()
        return {
            "filename": Path(filename).name,
            "extension": ext,
            "file_type": file_type,
            "category": "drill" if is_drill_layer else "gerber",
            "layer": x2_layer,
            "confidence": 100,
            "source": "Gerber X2 FileFunction",
        }

    if file_type == "Excellon":
        layer = classify_drill_filename(filename)
        confidence = 92 if layer != "Drill" else 80
        return {
            "filename": Path(filename).name,
            "extension": ext,
            "file_type": file_type,
            "category": "drill",
            "layer": layer,
            "confidence": confidence,
            "source": "Excellon content + filename",
        }

    if file_type == "Support":
        layer = classify_filename(filename) or "Documentation"
        cat = "drill" if layer in {"Drill", "PTH Drill", "NPTH Drill"} else "support"
        return {
            "filename": Path(filename).name,
            "extension": ext,
            "file_type": file_type,
            "category": cat,
            "layer": layer,
            "confidence": 95,
            "source": "support/document file",
        }

    if ext in EXTENSION_LAYER_MAP:
        layer = EXTENSION_LAYER_MAP[ext]
        confidence = 96
        source = "standard extension"
    else:
        layer = classify_filename(filename)
        confidence = 90
        source = "filename semantics"

    category = "drill" if layer in {"Drill", "PTH Drill", "NPTH Drill"} else "gerber" if file_type == "Gerber" else "other"
    if layer:
        return {
            "filename": Path(filename).name,
            "extension": ext,
            "file_type": file_type,
            "category": category,
            "layer": layer,
            "confidence": confidence,
            "source": source,
        }

    # Supplied main.py label is useful only if it is not generic.
    supplied = str(supplied_layer or "").strip()
    if supplied and supplied.lower() not in {
        "unknown", "other", "other gerber", "unknown gerber"
    }:
        return {
            "filename": Path(filename).name,
            "extension": ext,
            "file_type": file_type,
            "layer": supplied,
            "confidence": 75,
            "source": "supplied layer metadata",
        }

    return {
        "filename": Path(filename).name,
        "extension": ext,
        "file_type": file_type,
        "layer": "Other Gerber" if file_type == "Gerber" else "Unknown",
        "confidence": 0,
        "source": "no reliable layer identifier",
    }


# ---------------------------------------------------------------------------
# QUICK SELF-TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    examples = [
        "board.GTL",
        "board.GBL",
        "board.GTS",
        "board.GBS",
        "board.GTO",
        "board.GBO",
        "board.GTP",
        "board.GBP",
        "board.GM1",
        "board.GD1",
        "board.G1",
        "board.G2",
        "board_Copper_Signal_Top.gbr",
        "board_Copper_Signal_Bot.gbr",
        "board_Legend_Top.gbr",
        "board_Legend_Bot.gbr",
        "board_Soldermask_Top.gbr",
        "board_Soldermask_Bot.gbr",
        "board_Paste_Top.gbr",
        "board_Paste_Bot.gbr",
        "board_Profile.gbr",
        "board_PTH_Drill.gbr",
        "board_NPTH_Drill.gbr",
        "board.drl",
        "board.xln",
        "board.txt",
    ]

    for item in examples:
        print(f"{item:45} -> {classify_file(item)['layer']}")
