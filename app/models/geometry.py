from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Point:
    x: float
    y: float


@dataclass
class Segment:
    start: Point
    end: Point
    interpolation: str = "linear"   # linear, clockwise_arc, counterclockwise_arc

    center_offset_x: Optional[float] = None
    center_offset_y: Optional[float] = None


@dataclass
class Contour:
    segments: list[Segment] = field(default_factory=list)

    def is_closed(self, tolerance: float = 0.001) -> bool:
        if not self.segments:
            return False

        start = self.segments[0].start
        end = self.segments[-1].end

        return (
            abs(start.x - end.x) <= tolerance
            and abs(start.y - end.y) <= tolerance
        )

    def bounding_box(self):
        if not self.segments:
            return None

        points = []

        for segment in self.segments:
            points.append(segment.start)
            points.append(segment.end)

        x_values = [point.x for point in points]
        y_values = [point.y for point in points]

        return {
            "x_min": min(x_values),
            "x_max": max(x_values),
            "y_min": min(y_values),
            "y_max": max(y_values),
        }

    def dimensions(self):
        box = self.bounding_box()

        if not box:
            return None

        return {
            **box,
            "width_mm": box["x_max"] - box["x_min"],
            "height_mm": box["y_max"] - box["y_min"],
        }