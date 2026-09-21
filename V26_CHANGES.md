# V26 — G74 Single-Quadrant Arc Fix

The TB363 `TUSHAR_B363.SST` source declares `G74` single-quadrant arc mode. V25 reconstructed G03 arcs using the full normalized angular direction, which can turn intended 90-degree segments into 270-degree arcs. V26 detects G74 and reconstructs each raw G02/G03 using the shortest geometric arc (the intended quadrant segment), while preserving modal coordinates, I/J offsets, aperture widths, and all other V25 geometry.

This is a targeted arc-path fix; board bounds, drill registration, layer classification, copper/mask geometry, and macro handling are otherwise unchanged.
