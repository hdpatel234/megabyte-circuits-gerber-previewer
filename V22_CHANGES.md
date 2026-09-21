# V22 — True Gerber Geometry Normalizer

## Purpose
Fix the remaining circular/arc rendering problem without changing the board-boundary or drill-registration work from V21.

## Geometry rules
- Gerber `Arc` primitives are flattened in Python into Cartesian polylines before JSON reaches the browser.
- Gerber `Arc` primitives use a 0.5° maximum angular step and exact source start/end points.
- Arcs inside Gerber Regions are recursively flattened as part of region construction.
- Aperture-macro groups are recursively preserved as `compound` geometry instead of being mistaken for Regions.
- Macro `Outline` containers are preserved recursively.
- Ellipse, diamond, rounded/chamfered rectangle primitives are normalized to polygons.
- Gerber circles/flashes are retained as semantic `circle`/`flash` objects but rendered by a 96-segment polygon in the browser.
- Drill circles are also rendered by polygons.
- The browser contains no Canvas `arc()` call for Gerber or drill geometry.

## Compatibility
- Keeps V21 trusted board bounds.
- Keeps V21 no-hang drill registration.
- Keeps headerless TAP support.
- Keeps custom aperture-macro/copper flash preservation.
- Cache version is bumped to `2026-09-15-v22-true-geometry-normalizer` so old vector cache data is not reused.

## Validation performed
- Python source compiles with `py_compile`.
- Browser source contains no `.arc(` or `arc(` rendering call.
- Package excludes `__pycache__`.

## Important
This version changes geometry normalization/rendering only. It does not alter layer classification or board dimensions.
