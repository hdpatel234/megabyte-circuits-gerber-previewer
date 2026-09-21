from pathlib import Path
import re


def parse_coordinate(value, integer_digits, decimal_digits):
    """
    Convert Gerber coordinate string to decimal.

    Example with X45 format:

    2476500 -> 24.76500
    -4191000 -> -41.91000
    """

    if not value:
        return None

    sign = 1

    if value.startswith("-"):
        sign = -1
        value = value[1:]

    elif value.startswith("+"):
        value = value[1:]

    total_digits = integer_digits + decimal_digits

    value = value.zfill(total_digits)

    integer_part = value[:integer_digits]
    decimal_part = value[integer_digits:]

    return sign * (
        int(integer_part)
        + int(decimal_part) / (10 ** decimal_digits)
    )


def detect_format(content):
    """
    Detect Gerber coordinate format.

    Example:
    %FSLAX45Y45*%
    """

    x_integer_digits = 4
    x_decimal_digits = 4

    y_integer_digits = 4
    y_decimal_digits = 4

    unit = "MM"

    fs_match = re.search(
        r"%FS[A-Z]*X(\d)(\d)Y(\d)(\d)\*%",
        content,
        re.IGNORECASE
    )

    if fs_match:

        x_integer_digits = int(fs_match.group(1))
        x_decimal_digits = int(fs_match.group(2))

        y_integer_digits = int(fs_match.group(3))
        y_decimal_digits = int(fs_match.group(4))

    content_upper = content.upper()

    if "%MOIN" in content_upper:
        unit = "INCH"

    elif "%MOMM" in content_upper:
        unit = "MM"

    return {
        "x_integer_digits": x_integer_digits,
        "x_decimal_digits": x_decimal_digits,
        "y_integer_digits": y_integer_digits,
        "y_decimal_digits": y_decimal_digits,
        "unit": unit
    }


def parse_gerber_bounds(file_path: Path):
    """
    Parse Gerber board outline and calculate
    the bounding box from actual coordinate commands.

    Gerber header commands such as:
        %FSLAX45Y45*%

    are explicitly ignored.
    """

    try:

        content = file_path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        fmt = detect_format(content)

        coordinates_x = []
        coordinates_y = []

        # Split Gerber into commands
        commands = content.split("*")

        for command in commands:

            command = command.strip()

            if not command:
                continue

            # ------------------------------------------------
            # Ignore Gerber parameter/header commands
            # ------------------------------------------------

            if command.startswith("%"):
                continue

            # Ignore comments
            if command.startswith("G04"):
                continue

            # Only process commands containing real
            # Gerber drawing/movement coordinates.
            #
            # Examples:
            # G01X2476500Y-4191000D02
            # X10947400Y190500D01
            # ------------------------------------------------

            if "D01" not in command and "D02" not in command:
                continue

            x_match = re.search(
                r"X([+-]?\d+)",
                command
            )

            y_match = re.search(
                r"Y([+-]?\d+)",
                command
            )

            if x_match:

                x_value = parse_coordinate(
                    x_match.group(1),
                    fmt["x_integer_digits"],
                    fmt["x_decimal_digits"]
                )

                if x_value is not None:
                    coordinates_x.append(x_value)

            if y_match:

                y_value = parse_coordinate(
                    y_match.group(1),
                    fmt["y_integer_digits"],
                    fmt["y_decimal_digits"]
                )

                if y_value is not None:
                    coordinates_y.append(y_value)

        # --------------------------------------------
        # Validation
        # --------------------------------------------

        if not coordinates_x or not coordinates_y:

            return {
                "error": "No valid board coordinates found."
            }

        x_min = min(coordinates_x)
        x_max = max(coordinates_x)

        y_min = min(coordinates_y)
        y_max = max(coordinates_y)

        width = x_max - x_min
        height = y_max - y_min

        # Convert inch Gerber coordinates to mm
        if fmt["unit"] == "INCH":

            x_min *= 25.4
            x_max *= 25.4

            y_min *= 25.4
            y_max *= 25.4

            width *= 25.4
            height *= 25.4

        return {

            "units": "mm",

            "coordinate_format": {
                "x": (
                    f'{fmt["x_integer_digits"]}.'
                    f'{fmt["x_decimal_digits"]}'
                ),
                "y": (
                    f'{fmt["y_integer_digits"]}.'
                    f'{fmt["y_decimal_digits"]}'
                )
            },

            "x_min": round(x_min, 5),
            "x_max": round(x_max, 5),

            "y_min": round(y_min, 5),
            "y_max": round(y_max, 5),

            "width_mm": round(width, 5),
            "height_mm": round(height, 5),

            "area_mm2": round(
                width * height,
                4
            )
        }

    except Exception as e:

        return {
            "error": str(e)
        }