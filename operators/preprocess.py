from __future__ import annotations

import math

from PIL import Image

from core.context import Frame, FrameSet, TransformStep


_INTERPOLATION = {
    "nearest": Image.Resampling.NEAREST,
    "bilinear": Image.Resampling.BILINEAR,
    "bicubic": Image.Resampling.BICUBIC,
}


def image_resize(inputs, params, services, node_id):
    frames = inputs["frames"]
    mode = params["mode"]
    interpolation = _INTERPOLATION[params["interpolation"]]
    output = []
    for frame in frames.items:
        width, height = frame.image.size
        if mode == "identity":
            output.append(frame)
            continue
        if mode == "long_side":
            scale = params["long_side"] / max(width, height)
            target = (max(1, round(width * scale)), max(1, round(height * scale)))
            image = frame.image.resize(target, interpolation)
            step = TransformStep(
                "resize_long_side",
                {
                    "source_size": [width, height],
                    "target_size": list(target),
                    "pixel_scale": [target[0] / width, target[1] / height],
                },
            )
        elif mode == "stretch":
            target = (params["width"], params["height"])
            if not all(target):
                raise ValueError("stretch mode requires width and height")
            image = frame.image.resize(target, interpolation)
            step = TransformStep(
                "resize_stretch",
                {
                    "source_size": [width, height],
                    "target_size": list(target),
                    "pixel_scale": [target[0] / width, target[1] / height],
                },
            )
        elif mode == "contain":
            target_width = params["width"]
            target_height = params["height"]
            if not target_width or not target_height:
                raise ValueError("contain mode requires width and height")
            scale = min(target_width / width, target_height / height)
            resized = frame.image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                interpolation,
            )
            image = Image.new("RGB", (target_width, target_height), "black")
            left = (target_width - resized.width) // 2
            top = (target_height - resized.height) // 2
            right_padding = target_width - resized.width - left
            bottom_padding = target_height - resized.height - top
            image.paste(resized, (left, top))
            step = TransformStep(
                "resize_contain",
                {
                    "source_size": [width, height],
                    "content_size": [resized.width, resized.height],
                    "target_size": [target_width, target_height],
                    "padding": [left, top, right_padding, bottom_padding],
                    "pixel_scale": [resized.width / width, resized.height / height],
                },
            )
        else:
            raise ValueError(f"unsupported resize mode: {mode}")
        transform = frame.transform.append(step)
        output.append(Frame(
            image=image,
            original_size=frame.original_size,
            frame_index=frame.frame_index,
            timestamp=frame.timestamp,
            source_rect=transform.to_original_bbox((0.0, 0.0, 1.0, 1.0)),
            transform=transform,
            source_entity_id=frame.source_entity_id,
        ))
    return FrameSet(
        output,
        source_path=frames.source_path,
        source_kind=frames.source_kind,
        source_fps=frames.source_fps,
    )


def _tile_positions(length: int, tile: int, overlap: float) -> list[int]:
    if length <= tile:
        return [0]
    stride = max(1, round(tile * (1 - overlap)))
    positions = list(range(0, length - tile + 1, stride))
    last = length - tile
    if positions[-1] != last:
        positions.append(last)
    return positions


def image_tile(inputs, params, services, node_id):
    frames = inputs["frames"]
    tile_width = params["tile_width"]
    tile_height = params["tile_height"]
    overlap_x = float(params.get("overlap_x", params.get("overlap", 0.2)))
    overlap_y = float(params.get("overlap_y", params.get("overlap", 0.2)))
    output = []
    for frame in frames.items:
        if params["include_full_frame"]:
            output.append(frame)
        width, height = frame.image.size
        for y in _tile_positions(height, tile_height, overlap_y):
            for x in _tile_positions(width, tile_width, overlap_x):
                right = min(width, x + tile_width)
                bottom = min(height, y + tile_height)
                tile_image = frame.image.crop((x, y, right, bottom))
                transform = frame.transform.append(TransformStep(
                    "tile",
                    {
                        "parent_size": [width, height],
                        "crop_box": [x, y, right, bottom],
                    },
                ))
                source_rect = transform.to_original_bbox(
                    (0.0, 0.0, 1.0, 1.0)
                )
                output.append(
                    Frame(
                        image=tile_image,
                        original_size=frame.original_size,
                        frame_index=frame.frame_index,
                        timestamp=frame.timestamp,
                        source_rect=source_rect,
                        transform=transform,
                        source_entity_id=frame.source_entity_id,
                    )
                )
    return FrameSet(
        output,
        source_path=frames.source_path,
        source_kind=frames.source_kind,
        source_fps=frames.source_fps,
    )


def _intersection_area(a, b):
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def object_crop(inputs, params, services, node_id):
    frames = inputs["frames"]
    objects = inputs["objects"]
    padding = float(params.get("padding_fraction", 0.0))
    rx0, ry0, rx1, ry1 = params.get(
        "subject_region", [0.0, 0.0, 1.0, 1.0]
    )
    output = []
    frames_by_index = {}
    for frame in frames.items:
        frames_by_index.setdefault(frame.frame_index, []).append(frame)
    for item in objects.items:
        candidates = frames_by_index.get(item.frame_index, [])
        if not candidates:
            continue
        frame = max(
            candidates,
            key=lambda value: _intersection_area(value.source_rect, item.bbox),
        )
        current = frame.transform.from_original_bbox(item.bbox)
        width, height = frame.image.size
        x0, y0, x1, y1 = current
        subject_width = x1 - x0
        subject_height = y1 - y0
        x0, y0, x1, y1 = (
            x0 + rx0 * subject_width,
            y0 + ry0 * subject_height,
            x0 + rx1 * subject_width,
            y0 + ry1 * subject_height,
        )
        pad_x = (x1 - x0) * padding
        pad_y = (y1 - y0) * padding
        x0, y0 = max(0.0, x0 - pad_x), max(0.0, y0 - pad_y)
        x1, y1 = min(1.0, x1 + pad_x), min(1.0, y1 + pad_y)
        left, top = int(round(x0 * width)), int(round(y0 * height))
        right, bottom = int(round(x1 * width)), int(round(y1 * height))
        if right <= left or bottom <= top:
            continue
        crop_box = [left, top, right, bottom]
        transform = frame.transform.append(TransformStep(
            "object_crop",
            {"parent_size": [width, height], "crop_box": crop_box},
        ))
        output.append(Frame(
            image=frame.image.crop(tuple(crop_box)),
            original_size=frame.original_size,
            frame_index=frame.frame_index,
            timestamp=frame.timestamp,
            source_rect=transform.to_original_bbox((0.0, 0.0, 1.0, 1.0)),
            transform=transform,
            source_entity_id=item.track_id or item.id,
        ))
    return FrameSet(
        output,
        source_path=frames.source_path,
        source_kind=frames.source_kind,
        source_fps=frames.source_fps,
    )
