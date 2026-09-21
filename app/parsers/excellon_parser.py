from pathlib import Path
import re


def parse_excellon(file_path: Path):
    """
    Basic Excellon drill parser.

    Returns:
    - drill tools
    - drill diameter for each tool
    - drill hit count for each tool
    """

    tools = {}
    current_tool = None
    total_hits = 0

    try:
        content = file_path.read_text(
            encoding="utf-8",
            errors="ignore"
        )

        lines = content.splitlines()

        for line in lines:
            line = line.strip().upper()

            if not line:
                continue

            # Detect tool definition
            # Examples:
            # T01C0.300
            # T01C0.012
            match = re.match(
                r"^T(\d+)C([0-9.]+)",
                line
            )

            if match:
                tool_number = f"T{match.group(1)}"
                diameter = float(match.group(2))

                tools[tool_number] = {
                    "diameter": diameter,
                    "hits": 0
                }

                continue

            # Detect tool selection
            # Example: T01
            match = re.match(
                r"^T(\d+)$",
                line
            )

            if match:
                current_tool = f"T{match.group(1)}"
                continue

            # Detect coordinate line
            # Example:
            # X12345Y67890
            if (
                current_tool
                and ("X" in line or "Y" in line)
            ):
                if current_tool in tools:
                    tools[current_tool]["hits"] += 1
                    total_hits += 1

        # Prepare tool list
        tool_list = []

        for tool, data in tools.items():
            tool_list.append({
                "tool": tool,
                "diameter": data["diameter"],
                "hits": data["hits"]
            })

        # Get minimum and maximum drill
        diameters = [
            tool["diameter"]
            for tool in tool_list
        ]

        return {
            "total_hits": total_hits,
            "tool_count": len(tool_list),
            "minimum_drill": min(diameters) if diameters else None,
            "maximum_drill": max(diameters) if diameters else None,
            "tools": tool_list
        }

    except Exception as e:
        return {
            "error": str(e)
        }