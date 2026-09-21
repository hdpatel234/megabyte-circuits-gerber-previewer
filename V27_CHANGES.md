# V27 — G74 Center-Sign Fix

Fixes the remaining SST circular/round geometry error.

Root cause: legacy Gerber G74 single-quadrant arcs encode I/J as magnitudes; the sign of the center offset is implied by the quadrant. V26 incorrectly used the written I/J signs directly. This produced incorrect arc centers for half of the quadrant segments.

V27:
- tests all valid +/- I/J center candidates
- requires equal start/end radius
- requires <=90 degree sweep in G74 mode
- preserves G02/G03 direction
- reconstructs all 92 G02/G03 commands in TUSHAR_B363.SST
- keeps existing board bounds and drill registration unchanged
