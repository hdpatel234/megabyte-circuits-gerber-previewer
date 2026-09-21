DFM V11 - KiCad Drill + Missing Pads Fix

Replace:
  gerber_viewer.py  <- gerber_viewer_v11.py
  gerber_viewer.html <- gerber_viewer(10)_bottom_mirror.html

What is fixed:
1. KiCad Excellon INCH absolute drill coordinates are converted to mm and
   kept unchanged when they already fit the Gerber board coordinate system.
   This prevents the old heuristic registration from moving valid drills.
2. KiCad custom aperture-macro pads are no longer silently dropped.
   RoundRectangle, Diamond, ChamferRectangle and polygon/macro-group
   geometry are converted to browser-safe vector polygons.
3. Existing bottom-side horizontal mirror is retained.
4. Existing colors and covered-copper rendering are retained.

For the supplied Gerber.zip:
- PTH drill file: 68 drill hits
- NPTH drill file: 4 drill hits
- Gerber copper contains many D03 macro flashes, including custom macro
  apertures; those were a major source of the missing pads.

No main.py change is required because it already imports build_viewer_data()
from gerber_viewer.py.
