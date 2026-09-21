# PCB DFM Analyzer / Gerber Viewer — Master Validation Checklist

**Current validated version:** V27 — G74 Center-Sign Fix  
**Date:** 2026-09-15

This is the master checklist for the PCB DFM Analyzer/viewer. New parser/viewer changes must preserve the checks below.

---

## 1. File Identification — CONTENT FIRST

- [x] Do not trust file extension alone.
- [x] Inspect file content before deciding Gerber vs drill/NC vs support file.
- [x] Same extension may represent different CAD-layer meanings.
- [x] Preserve original filename and source-layer identity.
- [x] Unknown/unrecognized files remain Unknown/Other rather than being guessed.
- [x] Do not classify a real drill file as Gerber merely because of its extension.
- [x] Do not classify a Gerber artwork file as drill merely because of its extension.

## 2. Supported PCB/CAD Layer Naming

- [x] Altium/Protel common layers: GTL, GBL, GTS, GBS, GTO, GBO, GTP, GBP.
- [x] Altium/Protel families: G*, GP*, GM*, GD*, GG*, GL*.
- [x] EAGLE: CMP, SOL, STC, STS, PLC, PLS, CRC, CRS, DRD.
- [x] EAGLE internal copper: LY2...LY15 and related internal-layer conventions.
- [x] Cadence/OrCAD-style artwork naming.
- [x] KiCad-style layer names such as F.Cu, B.Cu, F.Mask, B.Mask, F.SilkS, B.SilkS, F.Paste, B.Paste, Edge.Cuts.
- [x] Descriptive layer names such as Copper_Signal_Top, Legend_Top, Soldermask_Top, Paste_Top, Mechanical, Fab.
- [ ] Add and validate additional CAD-specific naming conventions when real sample files are received.

## 3. Gerber Source Format

- [x] Gerber units detected from source header.
- [x] Gerber coordinate format detected from FS.
- [x] Zero suppression detected.
- [x] Layer polarity LP D/C detected.
- [x] Modal X/Y coordinates supported.
- [x] D01 draw.
- [x] D02 move.
- [x] D03 flash.
- [x] G01 linear interpolation.
- [x] G02 clockwise arc.
- [x] G03 counter-clockwise arc.
- [x] G74 single-quadrant arc mode.
- [ ] Validate G75 multi-quadrant mode with dedicated samples.
- [x] Aperture definitions are not mistaken for plot coordinates.
- [x] Aperture widths are preserved.
- [x] Clear/dark polarity is retained in geometry.
- [x] Board-outline geometry may exist on a non-outline-named layer.

## 4. Gerber Apertures / Geometry

- [x] Circle apertures.
- [x] Rectangle apertures.
- [x] Obround apertures.
- [x] Polygon/region geometry.
- [x] Aperture macro / AMGroup geometry.
- [x] Macro compound primitives are recursively processed.
- [x] Macro flash geometry is not incorrectly treated as a Region.
- [x] Custom copper flash pads are preserved.
- [x] Arc geometry is flattened deterministically for browser rendering.
- [x] Browser rendering does not depend on Canvas arc() for Gerber arcs.
- [ ] Validate all uncommon aperture-macro primitive types with dedicated samples: Moire, Thermal, Donut, Butterfly, Slot and related custom shapes.
- [ ] Validate negative/clear macro primitives against source-rendered reference images.

## 5. G74 Single-Quadrant Arc Validation — V27

- [x] Detect G74.
- [x] Treat I/J as center-offset magnitudes where required by the legacy source.
- [x] Test possible I/J sign combinations.
- [x] Select center using start/end radius consistency.
- [x] Enforce single-quadrant sweep constraint.
- [x] Preserve G02/G03 direction.
- [x] Validate against actual TB363 SST source.
- [x] TB363 SST: 92 source G02/G03 arc commands accounted for.
- [x] Prevent accidental 270°/360° arcs.
- [x] Prevent large misplaced circles caused by wrong arc centers.

## 6. Board Profile / Dimensions

- [x] Detect board outline from dedicated profile files.
- [x] Detect board outline from embedded geometry on other layers.
- [x] Keep source layer identity unchanged when that layer also contains the outline.
- [x] Use trusted DFM board analysis for viewer board bounds.
- [x] Do not let arbitrary Gerber extents redefine board dimensions.
- [x] Preserve true board width/height.
- [x] Profile/outline overlay is independent from layer classification.
- [ ] Validate complex rounded/indented profiles across multiple real boards.
- [ ] Validate non-closed profile sources and report them explicitly.

## 7. Drill / NC / Excellon

- [x] Modern Excellon with M48 header.
- [x] METRIC / INCH detection.
- [x] LZ / TZ zero suppression.
- [x] FILE_FORMAT / FMAT handling.
- [x] Tool IDs normalized (T1/T01).
- [x] Tool definitions with F/S/C in different field orders.
- [x] Omitted X/Y modal coordinates.
- [x] Fixed-integer coordinate parsing using declared precision.
- [x] Headerless legacy TAP/NC drill detection by content.
- [x] Legacy TAP tool diameters such as T1C0.027F200S100.
- [x] Legacy TAP metric coordinate convention.
- [x] TB363 TAP: 135 drill hits / 6 tools.
- [x] Drill diameter is taken from the active tool.
- [x] Drill holes render above copper/mask so they remain visible.
- [x] PTH and NPTH can be represented separately.
- [ ] Validate routed slots / drill slots.
- [ ] Validate drill rotation/offset conventions on additional exporters.

## 8. Drill Registration

- [x] Independent drill coordinate normalization.
- [x] Gerber pad/circle reference detection.
- [x] Dedicated Drill Drawing reference preference.
- [x] Spatial-hash matching for performance.
- [x] No exhaustive O(drills × targets × scales) hang.
- [x] Bounded mirror/translation registration.
- [x] Confidence reporting.
- [x] Low-confidence transforms are rejected.
- [x] Raw drill coordinates preserved for diagnostics.
- [x] TB363 registration: 135/135 hits matched.
- [x] Registration must not change board dimensions.
- [ ] Validate multiple boards with rotated coordinate systems.

## 9. Layer Classification

- [x] Top Copper.
- [x] Bottom Copper.
- [x] Inner Copper.
- [x] Top/Bottom Solder Mask.
- [x] Top/Bottom Silkscreen.
- [x] Top/Bottom Paste.
- [x] Board Profile.
- [x] Drill / PTH / NPTH.
- [x] Drill Drawing / Drill Guide.
- [x] Other Gerber.
- [x] Preserve original source filename.
- [x] Do not convert useful unknown geometry into a guessed standard layer.

## 10. Viewer Rendering

- [x] Vector geometry rather than raster-only PNG viewing.
- [x] Top / Bottom / All / None controls.
- [x] Layer visibility controls.
- [x] Drill visibility.
- [x] Copper rendering.
- [x] Solder-mask rendering.
- [x] Silkscreen rendering.
- [x] Paste rendering.
- [x] Board profile overlay.
- [x] Macro flashes.
- [x] Arc geometry.
- [x] Compound geometry.
- [x] Browser DPR capped for performance.
- [x] requestAnimationFrame redraw scheduling.
- [x] GZip response compression.
- [x] Persistent viewer cache.
- [x] Cache version invalidation after geometry changes.
- [ ] Add optional exact source-render comparison mode.
- [ ] Add geometry diagnostics showing primitive counts by type.

## 11. Performance

- [x] Gerber parsing timing logged.
- [x] Drill parsing timing logged.
- [x] Reference-target extraction timing logged.
- [x] Drill-registration timing logged.
- [x] Total viewer-build timing logged.
- [x] Cached viewer requests return quickly.
- [x] Registration cannot hang on small or large target sets.
- [ ] Establish target performance benchmark for large production Gerber sets.

## 12. TB363 Golden Reference Board

Use TB363 as a regression test board.

- [x] Correct board shape visually matches reference.
- [x] Correct board dimensions preserved.
- [x] 8 viewer layers detected in the tested set.
- [x] 135 TAP drill hits.
- [x] 6 drill tools.
- [x] Top/bottom copper geometry visible.
- [x] Top/bottom mask geometry visible.
- [x] Top silkscreen geometry visible.
- [x] Custom/macro flashes visible.
- [x] Component round/notched silkscreen geometry validated against source.
- [x] G74 arc behavior validated.
- [x] No giant false circles/arcs.
- [ ] Final visual acceptance against the supplied correct Gerber-view reference after each geometry-engine change.

## 13. Regression Rule

Every future parser/viewer release must pass:

1. Existing TB363 regression.
2. Existing Fatocare regression.
3. Modern Excellon regression.
4. Headerless TAP regression.
5. Macro-flash regression.
6. Board-profile regression.
7. G74 arc regression.
8. Layer-classification regression.
9. Performance/no-hang regression.

**Rule:** A new fix must not solve one board by breaking a previously validated board or file format.

---

## Current Status

### Validated / Implemented
- Content-first file detection
- Global layer classification
- Vector Gerber viewer
- Macro flash handling
- Headerless TAP parsing
- Drill registration
- Trusted board bounds
- Arc flattening
- G74 single-quadrant arc recovery
- TB363 92-arc regression target

### Remaining Validation Work
- Uncommon aperture macro types
- G75 multi-quadrant samples
- Slots/routed drills
- Additional CAD exporter coordinate conventions
- Larger production-board performance benchmark
- Final golden-image comparison suite

**Golden rule:** source Gerber geometry is the authority. Never replace source geometry with a visual guess.
