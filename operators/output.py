from __future__ import annotations

import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from core.context import EventSet, Frame, FrameSet, RenderedMedia


def _font():
    for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, 18)
    return ImageFont.load_default()


def _draw_arrow(draw, start, end, *, color="cyan", width=4):
    draw.line([start, end], fill=color, width=width)
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return
    ux, uy = dx / length, dy / length
    head = min(16.0, max(8.0, length * 0.18))
    spread = head * 0.55
    base_x, base_y = end[0] - ux * head, end[1] - uy * head
    left = (base_x - uy * spread, base_y + ux * spread)
    right = (base_x + uy * spread, base_y - ux * spread)
    draw.polygon([end, left, right], fill=color)


def _label_position(anchor, index: int, line_height: int = 22):
    """Place labels sharing a top-left anchor on separate readable rows."""

    x, y = anchor
    return int(x), int(y + max(0, int(index)) * line_height)


def _active_values(values, frame):
    if values is None:
        return []
    return [
        item
        for item in values.items
        if item.frame_index is None or item.frame_index == frame.frame_index
    ]


def _region_centers(regions):
    if regions is None:
        return {}
    result = {}
    for region in regions.items:
        if region.points:
            result[region.id] = (
                sum(point[0] for point in region.points) / len(region.points),
                sum(point[1] for point in region.points) / len(region.points),
            )
    return result


def _annotate(
    frame,
    objects,
    regions,
    directions,
    measurements,
    events,
    params,
):
    image = frame.image.copy().convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font()
    active_events = [] if events is None else [
        event for event in events.items if event.start_time <= frame.timestamp <= event.end_time
    ]
    active_by_entity = {event.entity_id: event.label for event in active_events}
    if objects is not None:
        label_rows = {}
        object_items = []
        for entity in objects.items:
            object_items.extend(entity.history if hasattr(entity, "history") else [entity])
        for item in object_items:
            if item.frame_index != frame.frame_index:
                continue
            width, height = image.size
            raw_x0, raw_y0, raw_x1, raw_y1 = item.bbox
            x0, x1 = sorted((raw_x0, raw_x1))
            y0, y1 = sorted((raw_y0, raw_y1))
            box = (round(x0 * width), round(y0 * height), round(x1 * width), round(y1 * height))
            event_label = active_by_entity.get(item.track_id or item.id)
            color = "orange" if event_label else "red"
            draw.rectangle(box, outline=color, width=4 if event_label else 3)
            if params["show_labels"]:
                suffix = f" [{item.track_id}]" if params.get("show_track_id") and item.track_id else ""
                event_suffix = f" {event_label}" if event_label else ""
                anchor = (box[0], max(0, box[1] - 22))
                row = label_rows.get(anchor, 0)
                label_rows[anchor] = row + 1
                draw.text(
                    _label_position(anchor, row),
                    item.label + suffix + event_suffix,
                    fill=color,
                    font=font,
                )
        if params.get("show_trajectory"):
            grouped = {}
            for item in object_items:
                if item.track_id and item.frame_index <= frame.frame_index:
                    x0, y0, x1, y1 = item.bbox
                    grouped.setdefault(item.track_id, []).append(
                        (item.frame_index, (round((x0 + x1) * image.width / 2), round((y0 + y1) * image.height / 2)))
                    )
            for history in grouped.values():
                points = [point for _, point in sorted(history)]
                if len(points) > 1:
                    draw.line(points, fill="cyan", width=2)
    if regions is not None and params.get("show_regions", True):
        width, height = image.size
        for region in regions.items:
            polygon = [(round(x * width), round(y * height)) for x, y in region.points]
            if not polygon:
                continue
            draw.line(polygon + [polygon[0]], fill="yellow", width=3)
            draw.text(polygon[0], region.label, fill="yellow", font=font)
    if directions is not None and params.get("show_directions", True):
        region_centers = _region_centers(regions)
        for direction in _active_values(directions, frame):
            metadata = direction.metadata or {}
            if metadata.get("start") is not None and metadata.get("end") is not None:
                start_normalized = metadata["start"]
                end_normalized = metadata["end"]
            else:
                cx, cy = region_centers.get(direction.key, (0.5, 0.12))
                dx, dy = direction.value
                norm = math.hypot(dx, dy)
                if norm <= 1e-9:
                    continue
                dx, dy = dx / norm, dy / norm
                half_length = 0.10
                start_normalized = [cx - dx * half_length, cy - dy * half_length]
                end_normalized = [cx + dx * half_length, cy + dy * half_length]
            start = (
                round(min(1.0, max(0.0, start_normalized[0])) * image.width),
                round(min(1.0, max(0.0, start_normalized[1])) * image.height),
            )
            end = (
                round(min(1.0, max(0.0, end_normalized[0])) * image.width),
                round(min(1.0, max(0.0, end_normalized[1])) * image.height),
            )
            _draw_arrow(draw, start, end)
            if params.get("show_labels", True):
                draw.text((start[0], max(0, start[1] - 22)), direction.key, fill="cyan", font=font)
    if measurements is not None and params.get("show_measurements", True):
        active_measurements = _active_values(measurements, frame)
        if active_measurements:
            lines = [f"{item.key}: {item.value}" for item in active_measurements]
            line_height = 23
            widest = max((draw.textlength(line, font=font) for line in lines), default=0)
            left = max(4, round(image.width - widest - 18))
            top = 4
            bottom = top + line_height * len(lines) + 6
            draw.rectangle((left, top, image.width - 4, bottom), fill=(0, 0, 0))
            for index, line in enumerate(lines):
                draw.text(
                    (left + 7, top + 3 + index * line_height),
                    line,
                    fill="lime",
                    font=font,
                )
    global_labels = [event.label for event in active_events if event.entity_id == "global"]
    if global_labels:
        draw.text((8, 8), " | ".join(global_labels), fill="orange", font=font)
    return image


def _source_backed_frames(frames: FrameSet) -> FrameSet:
    """Rehydrate sampled frames from the uploaded media for source-size output.

    Detection frames may have been resized, padded, tiled, or cropped.  All
    operator results are already mapped back to source-normalized coordinates,
    so drawing on the uploaded pixels is both more faithful and avoids padding
    geometry leaking into the presentation layer.
    """

    if not frames.source_path:
        return frames
    source = Path(frames.source_path)
    if not source.is_file():
        raise ValueError(f"source media no longer exists: {source}")

    # A tiled/cropped FrameSet can contain several derived images for one source
    # frame.  Source presentation must emit that source frame only once.
    unique = []
    seen = set()
    for frame in frames.items:
        if frame.frame_index not in seen:
            unique.append(frame)
            seen.add(frame.frame_index)

    restored: list[Frame] = []
    if frames.source_kind == "image":
        source_image = Image.open(source).convert("RGB")
        for frame in unique:
            restored.append(
                Frame(
                    image=source_image.copy(),
                    original_size=source_image.size,
                    frame_index=frame.frame_index,
                    timestamp=frame.timestamp,
                    source_entity_id=frame.source_entity_id,
                )
            )
    elif frames.source_kind == "video":
        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise ValueError(f"cannot reopen source video for drawing: {source}")
        try:
            for frame in unique:
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(frame.frame_index))
                ok, bgr = capture.read()
                if not ok:
                    raise ValueError(
                        f"cannot read source video frame {frame.frame_index}: {source}"
                    )
                image = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
                restored.append(
                    Frame(
                        image=image,
                        original_size=image.size,
                        frame_index=frame.frame_index,
                        timestamp=frame.timestamp,
                        source_entity_id=frame.source_entity_id,
                    )
                )
        finally:
            capture.release()
    else:
        return frames
    return FrameSet(
        restored,
        source_path=frames.source_path,
        source_kind=frames.source_kind,
        source_fps=frames.source_fps,
    )


def _write_browser_playable_video(path, images, fps, output_size):
    """Write annotated video as H.264/yuv420p/faststart so browsers can play it.

    OpenCV's ``mp4v`` (MPEG-4 Part 2) files cannot be decoded by Chrome/Edge,
    which made annotated videos invisible in the Gradio UI. Prefer imageio's
    bundled ffmpeg (libx264); fall back to cv2 mp4v only when unavailable.
    """
    width, height = output_size
    try:
        import imageio.v2 as imageio

        even_size = (width - width % 2, height - height % 2)
        with imageio.get_writer(
            str(path),
            fps=fps,
            codec="libx264",
            quality=7,
            pixelformat="yuv420p",
            macro_block_size=1,
            output_params=["-movflags", "faststart"],
        ) as writer:
            for image in images:
                if image.size != even_size:
                    image = image.resize(even_size)
                writer.append_data(np.asarray(image))
        return
    except ImportError:
        pass
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        raise ValueError(f"cannot create annotated video: {path}")
    for image in images:
        if image.size != output_size:
            image = image.resize(output_size)
        writer.write(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
    writer.release()


def output_draw(inputs, params, services, node_id):
    frames = inputs["frames"]
    if not frames.items:
        raise ValueError("cannot draw an empty FrameSet")
    size_mode = params.get("output_size_mode", "source")
    if size_mode == "source":
        frames = _source_backed_frames(frames)
    frame = frames.items[0]
    objects = inputs.get("objects")
    regions = inputs.get("regions")
    directions = inputs.get("directions")
    measurements = inputs.get("measurements")
    events = inputs.get("events")
    services.output_dir.mkdir(parents=True, exist_ok=True)
    if size_mode == "source":
        output_size = tuple(frame.original_size)
    elif size_mode == "processed":
        output_size = tuple(frame.image.size)
    else:
        output_size = (
            int(params["output_width"]), int(params["output_height"])
        )
    if frames.source_kind == "video":
        path = services.output_dir / f"{node_id}.mp4"
        width, height = output_size
        fps_mode = params.get("output_fps_mode", "sample_timeline")
        if fps_mode == "fixed":
            fps = float(params["output_fps"])
        elif fps_mode == "source":
            fps = frames.source_fps or 2.0
        elif len(frames.items) > 1:
            intervals = [b.timestamp - a.timestamp for a, b in zip(frames.items, frames.items[1:]) if b.timestamp > a.timestamp]
            fps = 1.0 / (sum(intervals) / len(intervals)) if intervals else (frames.source_fps or 2.0)
        else:
            fps = frames.source_fps or 2.0
        annotated_images = []
        for video_frame in frames.items:
            image = _annotate(
                video_frame,
                objects,
                regions,
                directions,
                measurements,
                events,
                params,
            )
            if image.size != output_size:
                image = image.resize(output_size)
            annotated_images.append(image)
        _write_browser_playable_video(path, annotated_images, fps, output_size)
        return RenderedMedia(str(path), "video")
    image = _annotate(
        frame, objects, regions, directions, measurements, events, params
    )
    if image.size != output_size:
        image = image.resize(output_size)
    path = services.output_dir / f"{node_id}.png"
    image.save(path)
    return RenderedMedia(str(path), "image")


def output_alert(inputs, params, services, node_id):
    for event in inputs["events"].items:
        event.label = params["label"]
    return EventSet(list(inputs["events"].items))
