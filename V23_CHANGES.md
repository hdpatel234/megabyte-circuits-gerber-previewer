# DFM V23 — Raw Gerber Arc Recovery

## Why V23 exists

The supplied `TUSHAR_B363.SST` was inspected directly.

It is a legacy RS-274X Gerber silkscreen file:
- `%MOIN*%` — source units are inch
- `%FSLAN2X34Y34*%` — absolute coordinates, 2 integer / 4 fractional digits
- It contains **92 G02/G03 circular interpolation commands**
- Those arcs use:
  - **D42**: circular aperture 0.0120 in = 0.3048 mm, 48 arc strokes
  - **D61**: circular aperture 0.0100 in = 0.2540 mm, 16 arc strokes
  - **D62**: circular aperture 0.0080 in = 0.2032 mm, 28 arc strokes

These source arcs correspond to the curved silkscreen/orientation geometry that was missing in the previous viewer result.

## V23 fix

`gerber_viewer.py` now has a source-truth G02/G03 recovery path.

1. pcb-tools still parses the Gerber normally.
2. The original Gerber text is inspected independently.
3. The parser counts the actual G02/G03 commands.
4. If fewer arc polylines were exposed by pcb-tools than exist in the source, V23 reconstructs the missing arc strokes directly from:
   - modal X/Y coordinates
   - I/J center offsets
   - current D-code aperture
   - Gerber units
   - Gerber coordinate format
   - G02/G03 direction
   - LP polarity
5. Recovered arcs are converted to the same 0.5-degree polyline representation used by V22.
6. Cache version is bumped to V23 so old vector-cache data is not reused.

This is deliberately a fallback/validation path; it does not replace normal pcb-tools parsing.

## Validation

- Python compilation passed for all packaged Python files.
- The uploaded SST source produced:
  - raw G02/G03 count: 92
  - recovered arc primitives: 92
  - D42: 48
  - D61: 16
  - D62: 28
- No browser Canvas `arc()` rendering is required; the browser continues to render polylines.

## Install

Replace the files in your `I:\DFM` project with the files from this ZIP, then restart Uvicorn.

After opening the same project, the server should show an additional line similar to:

`[VIEWER ARC RECOVERY] TUSHAR_B363.SST: raw_g02_g03=92, parsed_arc_polylines=<n>, recovered=<n>`

If `parsed_arc_polylines` is already 92, recovery will be 0 because the parser already supplied all source arcs. If it is lower, the missing source arcs are added automatically.
