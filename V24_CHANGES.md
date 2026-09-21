# V24 — Source-Truth Gerber Arc Replacement

- Actual `TUSHAR_B363.SST` contains 92 G03 arc commands.
- V23 incorrectly counted every polyline as an arc, so raw recovery never ran.
- V24 marks pcb-tools Arc conversions explicitly and replaces those with raw G02/G03 source geometry.
- Cache version bumped to force regeneration.
- Board bounds/drill registration are unchanged.
