# DFM V25 — Correct Legacy Gerber Modal Coordinate Arc Recovery

## Root cause of V24 failure
V24 raw-arc recovery scanned arbitrary Gerber lines for X/Y. TUSHAR_B363.SST contains X/Y values inside `%ADD...X...*%` aperture definitions. Those parameter values contaminated the modal plot position, producing large incorrect silkscreen arcs.

## Fix
- Ignore `%...%` parameter blocks, G04 comments and `*` records when recovering plot geometry.
- Update modal X/Y only on actual G01/G02/G03/D01/D02/D03 plotting commands.
- Save the previous modal position before processing an arc.
- Interpret I/J as offsets from the arc START position, as required by the Gerber format.
- Keep source units/FS precision and aperture widths unchanged.
- Preserve the existing V24 board bounds, drill registration, macro handling and cache architecture.

## Expected TB363 SST
- 92 G02/G03 source arcs recovered.
- D42 = 48 arcs, D61 = 16 arcs, D62 = 28 arcs.
- No coordinate contamination from `%ADD...X...*%` definitions.
- Recovered arc endpoint bounds are approximately 0.0474..3.1905 inch by 0.5100..3.5744 inch before inch-to-mm normalization.
