# DFM Viewer Fixed v3

Files:
- main.py
- gerber_viewer.py
- gerber_viewer.html
- INSTALL_FIXED.ps1

The installer avoids the previous "Cannot overwrite ... with itself" error.
It detects when the package is already inside the target directory.

The viewer now:
- uses pcb-tools geometry bounding boxes for board dimensions;
- flattens Gerber arcs in Python;
- fills Gerber regions instead of drawing region centerlines;
- renders rectangle/obround flashes;
- keeps clear/negative features isolated to their own layer;
- preserves a board outline as the primary viewport bounds;
- reports geometry bounds in the viewer API;
- parses Excellon drills with pcb-tools first, with text fallback.
