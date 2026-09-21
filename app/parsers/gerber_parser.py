from pathlib import Path
import re

from app.models.geometry import Point, Segment, Contour


def detect_gerber_format(content: str):

    x_integer = 4
    x_decimal = 4

    y_integer = 4
    y_decimal = 4

    unit = "mm"

    match = re.search(
        r"%FS[A-Z]*X(\d)(\d)Y(\d)(\d)\*%",
        content,
        re.IGNORECASE
    )

    if match:
        x_integer = int(match.group(1))
        x_decimal = int(match.group(2))

        y_integer = int(match.group(3))
        y_decimal = int(match.group(4))

    if "%MOIN" in content.upper():
        unit = "inch"

    elif "%MOMM" in content.upper():
        unit = "mm"

    return {
        "x_integer": x_integer,
        "x_decimal": x_decimal,
        "y_integer": y_integer,
        "y_decimal": y_decimal,
        "unit": unit
    }


def parse_coordinate(
    value: str,
    integer_digits: int,
    decimal_digits: int
):

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

    result = (
        int(integer_part)
        +
        int(decimal_part) / (10 ** decimal_digits)
    )

    return sign * result


def parse_gerber(file_path: Path):

    content = file_path.read_text(
        encoding="utf-8",
        errors="ignore"
    )

    fmt = detect_gerber_format(content)

    contours = []

    current_contour = None
    current_point = None

    commands = content.split("*")

    interpolation = "linear"

    for command in commands:

        command = command.strip()

        if not command:
            continue

        # Ignore parameter commands
        if command.startswith("%"):
            continue

        # Ignore comments
        if command.startswith("G04"):
            continue

        # Interpolation mode
        if "G01" in command:
            interpolation = "linear"

        elif "G02" in command:
            interpolation = "clockwise_arc"

        elif "G03" in command:
            interpolation = "counterclockwise_arc"

        x_match = re.search(
            r"X([+-]?\d+)",
            command
        )

        y_match = re.search(
            r"Y([+-]?\d+)",
            command
        )

        if not x_match and not y_match:
            continue

        x = (
            parse_coordinate(
                x_match.group(1),
                fmt["x_integer"],
                fmt["x_decimal"]
            )
            if x_match
            else current_point.x if current_point else None
        )

        y = (
            parse_coordinate(
                y_match.group(1),
                fmt["y_integer"],
                fmt["y_decimal"]
            )
            if y_match
            else current_point.y if current_point else None
        )

        if x is None or y is None:
            continue

        # Convert inches to mm
        if fmt["unit"] == "inch":
            x *= 25.4
            y *= 25.4

        new_point = Point(x=x, y=y)

        # D02 = move
        if "D02" in command:

            if current_contour and current_contour.segments:
                contours.append(current_contour)

            current_contour = Contour()
            current_point = new_point

            continue

        # D01 = draw
        if "D01" in command:

            if current_point is None:

                current_point = new_point
                continue

            if current_contour is None:
                current_contour = Contour()

            segment = Segment(
                start=current_point,
                end=new_point,
                interpolation=interpolation
            )

            current_contour.segments.append(segment)

            current_point = new_point

    # Add final contour
    if current_contour and current_contour.segments:
        contours.append(current_contour)

    return {
        "format": fmt,
        "contours": contours
    }