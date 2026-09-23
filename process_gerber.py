#!/usr/bin/env python3
"""
Standalone Gerber Archive Processing & Preview Rendering CLI
============================================================

Usage:
    python process_gerber.py <path_to_gerber_archive.zip_or_rar_or_folder> [output_directory]

Description:
    1. Extracts the ZIP/RAR archive into an isolated temporary location.
    2. Detects and classifies Gerber & NC Drill layers using global layer classifier.
    3. Calculates board bounding box, physical dimensions, and layer counts.
    4. Renders high-resolution 2D Front (Top) and Back (Bottom) PCB preview PNG images.
    5. Outputs structured job summary JSON and image paths.
"""

import sys
import os
import time
import json
import uuid
import shutil
import zipfile
import argparse
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pcb_global_layer_classifier import classify_file, GERBER_EXTENSIONS, DRILL_EXTENSIONS
from main import extract_archive, get_project_files, analyze_project_board, build_pcb_summary
from pcb_renderer import generate_pcb_previews


def process_gerber_archive(archive_path: str, output_dir: str = None) -> dict:
    start_time = time.time()
    archive_path = Path(archive_path).resolve()
    
    if not archive_path.exists():
        raise FileNotFoundError(f"Input file or directory does not exist: {archive_path}")

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    if not output_dir:
        output_dir = BASE_DIR / "projects" / job_id
    else:
        output_dir = Path(output_dir).resolve() / job_id

    output_dir.mkdir(parents=True, exist_ok=True)
    extracted_dir = output_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n========================================================")
    print(f" JOB ID: {job_id}")
    print(f" INPUT ARCHIVE: {archive_path.name}")
    print(f" OUTPUT DIR: {output_dir}")
    print(f"========================================================\n")

    # 1. Extract Archive
    if archive_path.is_dir():
        for item in archive_path.rglob("*"):
            if item.is_file():
                rel = item.relative_to(archive_path)
                dest = extracted_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
    else:
        print(f"[1/5] Extracting archive...")
        success, msg = extract_archive(archive_path, extracted_dir)
        if not success:
            raise RuntimeError(f"Failed to extract archive: {msg}")

    # 2. Detect and Classify Gerber Files
    print(f"[2/5] Detecting and classifying Gerber layers...")
    project_files = get_project_files(extracted_dir)
    
    print(f"\n--- DETECTED LAYERS ({len(project_files)} files) ---")
    classified_summary = []
    for item in project_files:
        fname = item.get("filename")
        layer = item.get("layer")
        cat = item.get("category")
        print(f"  • {fname:35s} -> [{cat.upper()}] {layer}")
        classified_summary.append({"filename": fname, "layer": layer, "category": cat})

    # 3. Analyze Geometry & Board Dimensions
    print(f"\n[3/5] Calculating PCB geometry & bounding box...")
    board_info = analyze_project_board(extracted_dir)
    
    width_mm = board_info.get("width_mm", 0.0)
    height_mm = board_info.get("height_mm", 0.0)
    width_in = board_info.get("width_in", 0.0)
    height_in = board_info.get("height_in", 0.0)
    layer_count = board_info.get("layer_count", 0)

    print(f"  • Dimensions: {width_mm:.2f} x {height_mm:.2f} mm ({width_in:.2f} x {height_in:.2f} inches)")
    print(f"  • Copper Layers: {layer_count}")
    print(f"  • Bounds: X[{board_info.get('min_x', 0):.2f}, {board_info.get('max_x', 0):.2f}] Y[{board_info.get('min_y', 0):.2f}, {board_info.get('max_y', 0):.2f}]")

    # 4. Render PCB Previews
    print(f"\n[4/5] Rendering 2D Front & Back PCB previews...")
    renders_dir = output_dir / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)

    rendered_files = generate_pcb_previews(output_dir, extracted_dir, project_files)
    
    top_preview = renders_dir / "pcb_top_2d.png"
    bottom_preview = renders_dir / "pcb_bottom_2d.png"

    print(f"\n[5/5] Finalizing output...")
    elapsed = time.time() - start_time
    
    summary_data = {
        "job_id": job_id,
        "archive_name": archive_path.name,
        "status": "completed",
        "processing_time_sec": round(elapsed, 3),
        "board_size": {
            "width_mm": width_mm,
            "height_mm": height_mm,
            "width_in": width_in,
            "height_in": height_in,
        },
        "layer_count": layer_count,
        "detected_files": classified_summary,
        "renders": {
            "top_2d": str(top_preview) if top_preview.exists() else None,
            "bottom_2d": str(bottom_preview) if bottom_preview.exists() else None,
        }
    }

    summary_file = output_dir / "job_summary.json"
    summary_file.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")

    print(f"\n========================================================")
    print(f" PROCESSING COMPLETED IN {elapsed:.2f}s")
    print(f" Top 2D Preview   : {top_preview}")
    print(f" Bottom 2D Preview: {bottom_preview}")
    print(f" Job Summary JSON : {summary_file}")
    print(f"========================================================\n")

    return summary_data


def main():
    parser = argparse.ArgumentParser(description="Process Gerber archive and render PCB previews.")
    parser.add_argument("archive", help="Path to input Gerber ZIP/RAR archive or directory")
    parser.add_argument("output_dir", nargs="?", default=None, help="Optional output directory")
    
    args = parser.parse_args()
    try:
        process_gerber_archive(args.archive, args.output_dir)
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Processing failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
