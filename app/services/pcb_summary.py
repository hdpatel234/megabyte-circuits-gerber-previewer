def create_pcb_summary(detected_files):
    """
    Create a PCB summary from detected Gerber and drill files.
    """

    layers = [item["layer"] for item in detected_files]

    # Copper layers
    top_copper = "Top Copper" in layers
    bottom_copper = "Bottom Copper" in layers

    inner_copper_layers = [
        layer for layer in layers
        if "Inner Copper" in layer
    ]

    copper_layers = 0

    if top_copper:
        copper_layers += 1

    if bottom_copper:
        copper_layers += 1

    copper_layers += len(inner_copper_layers)

    # Drill files
    drill_files = [
        item for item in detected_files
        if item["category"] == "drill"
    ]

    return {
        "copper_layers": copper_layers,

        "top_copper": top_copper,
        "bottom_copper": bottom_copper,

        "inner_layers": len(inner_copper_layers),

        "board_outline_found":
            "Board Outline" in layers,

        "drill_files": len(drill_files),

        "top_solder_mask":
            "Top Solder Mask" in layers,

        "bottom_solder_mask":
            "Bottom Solder Mask" in layers,

        "top_silkscreen":
            "Top Silkscreen" in layers,

        "bottom_silkscreen":
            "Bottom Silkscreen" in layers
    }