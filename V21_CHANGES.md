# V21 — trusted board bounds + universal arc flattening

## Fixed

1. Viewer board size no longer comes from the union of all Gerber extents.
   It receives the same `analyze_project_board()` result used by the Analysis Result page.
2. This prevents fabrication frames, drawing rectangles, registration artwork,
   or other out-of-board geometry from expanding the viewport.
3. Viewer records outline provenance (`outline_source_file`, `outline_source_layer`).
4. Every pcb-tools Arc is flattened to a 1-degree polyline before browser rendering.
   Regions recursively use the same conversion, so no browser-side arc primitive is required.
5. Explicit Board Outline / Board Profile / Edge Cuts layers are still supported as fallback.
6. V20 robust multi-hole drill registration and macro-flash preservation are retained.

## Expected TB363 result

The viewer should use the same physical board bounds as Analysis Result (approximately 82.24 x 92.99 mm for the screenshot shown by the user), rather than the previous 95.308 x 138.585 mm artwork envelope.
