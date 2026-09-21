from pathlib import Path
import gerber


# ---------------------------------------------------------
# GERBER RENDERER
# ---------------------------------------------------------

def render_gerber_file(
    gerber_path: Path,
    output_path: Path
):
    """
    Render a single Gerber file to SVG.

    SVG is used first because it is lightweight and
    can later be converted to PNG.
    """

    try:

        # Read Gerber
        layer = gerber.read(str(gerber_path))

        # Render context
        ctx = gerber.render.GerberCairoContext()

        # Render layer
        ctx.render_layer(
            layer,
            settings=None,
            bounds=None
        )

        # Save SVG
        ctx.dump_svg(
            str(output_path)
        )

        return {
            "success": True,
            "file": gerber_path.name,
            "output": output_path.name
        }

    except Exception as e:

        return {
            "success": False,
            "file": gerber_path.name,
            "error": str(e)
        }


# ---------------------------------------------------------
# FIND GERBER FILES
# ---------------------------------------------------------

def is_gerber_file(filename: str):

    extensions = {

        ".gbr",
        ".gtl",
        ".gbl",

        ".gts",
        ".gbs",

        ".gto",
        ".gbo",

        ".gko",
        ".gm1",

        ".g1",
        ".g2",
        ".g3",
        ".g4",

        ".g55",
        ".g56",

        ".art"
    }

    return Path(filename).suffix.lower() in extensions


# ---------------------------------------------------------
# SANITIZE FILE NAME
# ---------------------------------------------------------

def sanitize_name(filename: str):

    name = Path(filename).stem.lower()

    replacements = {

        " ": "_",
        "-": "_",

        "gerber_": "",
        "layer": "",

    }

    for old, new in replacements.items():

        name = name.replace(
            old,
            new
        )

    return name


# ---------------------------------------------------------
# RENDER PROJECT
# ---------------------------------------------------------

def render_pcb_project(
    extracted_path: Path,
    project_path: Path,
    project_files: list
):

    # -----------------------------------------------------
    # CREATE OUTPUT DIRECTORY
    # -----------------------------------------------------

    output_path = (

        project_path
        / "output"

    )

    output_path.mkdir(

        exist_ok=True

    )


    # -----------------------------------------------------
    # CREATE LAYER DIRECTORY
    # -----------------------------------------------------

    layers_path = (

        output_path
        / "layers"

    )

    layers_path.mkdir(

        exist_ok=True

    )


    # -----------------------------------------------------
    # RESULT
    # -----------------------------------------------------

    result = {

        "success": True,

        "layers": [],

        "errors": []

    }


    # -----------------------------------------------------
    # LOOP THROUGH PROJECT FILES
    # -----------------------------------------------------

    for file_info in project_files:

        filename = (

            file_info
            .get("filename")

        )


        # Skip if missing
        if not filename:

            continue


        # Check Gerber
        if not is_gerber_file(

            filename

        ):

            continue


        # Full input path
        gerber_path = (

            extracted_path
            / filename

        )


        # Check exists
        if not gerber_path.exists():

            continue


        # Layer name
        layer_name = (

            file_info
            .get(
                "layer",
                "Unknown"
            )

        )


        # Output filename
        clean_name = (

            sanitize_name(
                filename
            )

        )


        output_file = (

            layers_path
            / f"{clean_name}.svg"

        )


        # -------------------------------------------------
        # RENDER
        # -------------------------------------------------

        render_result = (

            render_gerber_file(

                gerber_path,

                output_file

            )

        )


        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        if render_result.get(

            "success"

        ):

            result[
                "layers"
            ].append(

                {

                    "filename": filename,

                    "layer": layer_name,

                    "image": (

                        f"/projects/"
                        f"{project_path.name}"
                        f"/output/layers/"
                        f"{output_file.name}"

                    )

                }

            )


        # -------------------------------------------------
        # ERROR
        # -------------------------------------------------

        else:

            result[
                "errors"
            ].append(

                render_result

            )


    # -----------------------------------------------------
    # FINAL STATUS
    # -----------------------------------------------------

    if result["errors"]:

        result[
            "success"
        ] = False


    return result