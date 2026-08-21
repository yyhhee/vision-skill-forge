from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
from PIL import Image, ImageDraw, ImageFont

from .runtime import detect_media_type


@dataclass(frozen=True)
class AnnotationFrame:
    image: Image.Image
    media_type: str
    timestamp: float
    frame_index: int
    source_path: str


def _font():
    for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(path).is_file():
            return ImageFont.truetype(path, 18)
    return ImageFont.load_default()


def extract_annotation_frame(
    media_path: str | Path, timestamp: float = 0.0
) -> AnnotationFrame:
    path = Path(media_path).resolve()
    media_type = detect_media_type(path)
    if media_type == "image":
        with Image.open(path) as source:
            image = source.convert("RGB")
        return AnnotationFrame(image, "image", 0.0, 0, str(path))

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise ValueError(f"cannot open video: {path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0 or frame_count <= 0:
        capture.release()
        raise ValueError(f"video reports invalid metadata: {path}")
    requested = max(0.0, float(timestamp or 0.0))
    frame_index = min(frame_count - 1, max(0, round(requested * fps)))
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, bgr = capture.read()
    capture.release()
    if not ok:
        raise ValueError(
            f"cannot extract annotation frame {frame_index} from video: {path}"
        )
    image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    return AnnotationFrame(
        image,
        "video",
        frame_index / fps,
        frame_index,
        str(path),
    )


def normalize_canvas_point(
    x: float, y: float, canvas_width: float, canvas_height: float
) -> list[float]:
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("canvas dimensions must be positive")
    return [
        min(1.0, max(0.0, float(x) / float(canvas_width))),
        min(1.0, max(0.0, float(y) / float(canvas_height))),
    ]


def _pixel(point, size):
    return (
        round(min(1.0, max(0.0, point[0])) * size[0]),
        round(min(1.0, max(0.0, point[1])) * size[1]),
    )


def _rectangle_polygon(points):
    if len(points) != 2:
        return points
    (x0, y0), (x1, y1) = points
    return [
        [min(x0, x1), min(y0, y1)],
        [max(x0, x1), min(y0, y1)],
        [max(x0, x1), max(y0, y1)],
        [min(x0, x1), max(y0, y1)],
    ]


def _arrow(draw, start, end, color="cyan"):
    draw.line([start, end], fill=color, width=4)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return
    ux, uy = dx / length, dy / length
    head = min(16.0, max(8.0, length * 0.18))
    spread = head * 0.55
    base = (end[0] - ux * head, end[1] - uy * head)
    left = (base[0] - uy * spread, base[1] + ux * spread)
    right = (base[0] + uy * spread, base[1] - ux * spread)
    draw.polygon([end, left, right], fill=color)


def render_annotation_workspace(
    image: Image.Image,
    annotations: dict[str, Any] | None = None,
    *,
    draft_tool: str | None = None,
    draft_points: list[list[float]] | None = None,
) -> Image.Image:
    rendered = image.copy().convert("RGB")
    draw = ImageDraw.Draw(rendered)
    font = _font()
    data = annotations or {}
    for region in data.get("regions", []):
        points = region.get("points", [])
        if region.get("shape") == "rectangle":
            points = _rectangle_polygon(points)
        pixels = [_pixel(point, rendered.size) for point in points]
        if len(pixels) >= 2:
            draw.line(pixels + [pixels[0]], fill="yellow", width=3)
            draw.text(
                pixels[0], region.get("label") or region.get("id", "region"),
                fill="yellow", font=font,
            )
    for direction in data.get("directions", []):
        start = direction.get("start")
        end = direction.get("end")
        if start is None or end is None:
            continue
        start_pixel, end_pixel = _pixel(start, rendered.size), _pixel(end, rendered.size)
        _arrow(draw, start_pixel, end_pixel)
        draw.text(start_pixel, direction.get("key", "direction"), fill="cyan", font=font)

    draft = draft_points or []
    draft_pixels = [_pixel(point, rendered.size) for point in draft]
    for point in draft_pixels:
        draw.ellipse(
            (point[0] - 4, point[1] - 4, point[0] + 4, point[1] + 4),
            fill="magenta",
        )
    if draft_tool == "direction" and len(draft_pixels) == 2:
        _arrow(draw, draft_pixels[0], draft_pixels[1], "magenta")
    elif len(draft_pixels) >= 2:
        line = list(draft_pixels)
        if draft_tool == "rectangle" and len(draft) == 2:
            line = [_pixel(point, rendered.size) for point in _rectangle_polygon(draft)]
            line.append(line[0])
        elif draft_tool == "polygon" and len(draft_pixels) >= 3:
            line.append(line[0])
        draw.line(line, fill="magenta", width=3)
    return rendered


def annotations_from_package(package, media_type: str) -> dict[str, Any]:
    variant = package.variants.get(media_type)
    if variant is None or variant.status == "unsupported":
        return {"regions": [], "directions": []}
    regions: list[dict[str, Any]] = []
    directions: list[dict[str, Any]] = []
    for node in variant.nodes:
        if node.op == "region.manual@1.0" and node.params.get("points"):
            regions.append({
                "id": node.id,
                "label": node.id,
                "shape": node.params.get("shape", "polygon"),
                "points": node.params["points"],
            })
        elif node.op == "region.manual_set@1.0":
            regions.extend(node.params.get("regions", []))
        elif node.op == "direction.manual@1.0":
            if node.params.get("start") is not None and node.params.get("end") is not None:
                directions.append({
                    "key": "global",
                    "start": node.params["start"],
                    "end": node.params["end"],
                })
        elif node.op == "direction.manual_set@1.0":
            directions.extend(
                {
                    "key": item["key"],
                    "start": item["start"],
                    "end": item["end"],
                }
                for item in node.params.get("directions", [])
                if item.get("start") is not None and item.get("end") is not None
            )
    return {"regions": regions, "directions": directions}


__all__ = [
    "AnnotationFrame",
    "annotations_from_package",
    "extract_annotation_frame",
    "normalize_canvas_point",
    "render_annotation_workspace",
]
