# DFM V20 Validation Checklist

## Parser
- [ ] Content-first Gerber / Excellon / legacy TAP detection
- [ ] Headerless TAP: 135 hits / 6 tools for TB363 test file
- [ ] TAP coordinates: fixed 6 digits -> 3 decimal mm
- [ ] TAP tool C values: inch -> mm
- [ ] Omitted X/Y coordinate reuse

## Geometry
- [ ] Gerber units / FS format / polarity retained
- [ ] Aperture macros preserved as compound geometry
- [ ] Custom copper flashes visible
- [ ] Board profile detected independently of source layer name
- [ ] Board dimensions come from profile

## Drill registration
- [ ] Raw drill center preserved as `raw_center`
- [ ] Dedicated Drill Drawing centers preferred
- [ ] Drill Drawing centers cross-checked against copper/mask
- [ ] Copper/mask feature fallback available
- [ ] Registration uses bounded spatial matching only
- [ ] Translation / mirror / scale candidates are globally scored
- [ ] At least 4 matched holes and >=15% coverage required
- [ ] Mean registration error <= 0.12 mm required for acceptance
- [ ] Low-confidence transforms are rejected, not silently applied
- [ ] Registration timing printed per drill layer

## Performance
- [ ] Reference extraction timing printed
- [ ] Registration timing printed
- [ ] Total viewer build timing printed
- [ ] V20 cache version invalidates V19 geometry
- [ ] No exhaustive drill-target registration loops remain

## TB363 visual acceptance
- [ ] Drill centers coincide with actual PCB hole centers
- [ ] PTH drill sits inside its copper annular pad
- [ ] NPTH drill has no false plated ring
- [ ] Drill Drawing is not mistaken for actual NC drill
- [ ] Top and Bottom views preserve alignment
