from __future__ import annotations

from core.context import ConditionSet, TimedValue


def _matches_color(
    h: int, s: int, v: int, color: str, *, tolerance: str = "strict"
) -> bool:
    # Raw whole-box colour filters need narrow HSV bins.  Once Rex has
    # already grounded a *named colour attribute*, the pixels only
    # corroborate that evidence: compression, illumination and cameras often
    # move a real colour across one neighbouring hue boundary.  The semantic
    # ranges below widen every colour family by a small, bounded amount while
    # retaining separate black/white/grey and brightness rules.  They are not
    # used for a standalone image-only colour decision.
    strict_rules = {
        "white": lambda: s <= 55 and v >= 170,
        "black": lambda: v <= 65,
        "gray": lambda: s <= 55 and 65 < v < 170,
        "red": lambda: (h <= 8 or h >= 246) and s >= 75 and v >= 65,
        "orange": lambda: 9 <= h < 28 and s >= 75 and v >= 140,
        "yellow": lambda: 28 <= h <= 60 and s >= 65 and v >= 80,
        "green": lambda: 61 <= h <= 115 and s >= 55 and v >= 55,
        "cyan": lambda: 116 <= h <= 145 and s >= 55 and v >= 55,
        "blue": lambda: 146 <= h <= 185 and s >= 55 and v >= 55,
        "purple": lambda: 186 <= h <= 220 and s >= 45 and v >= 55,
        "pink": lambda: 221 <= h <= 245 and s >= 40 and v >= 120,
        "brown": lambda: 9 <= h < 28 and s >= 55 and 45 <= v < 140,
    }
    semantic_rules = {
        "white": lambda: s <= 70 and v >= 155,
        "black": lambda: v <= 80,
        "gray": lambda: s <= 70 and 55 < v < 185,
        "red": lambda: (h <= 16 or h >= 238) and s >= 65 and v >= 55,
        "orange": lambda: 5 <= h < 36 and s >= 65 and v >= 120,
        "yellow": lambda: 20 <= h <= 68 and s >= 65 and v >= 80,
        "green": lambda: 53 <= h <= 123 and s >= 45 and v >= 45,
        "cyan": lambda: 108 <= h <= 153 and s >= 45 and v >= 45,
        "blue": lambda: 138 <= h <= 193 and s >= 45 and v >= 45,
        "purple": lambda: 178 <= h <= 228 and s >= 35 and v >= 45,
        "pink": lambda: 213 <= h <= 253 and s >= 30 and v >= 105,
        "brown": lambda: 5 <= h < 32 and s >= 45 and 40 <= v < 155,
    }
    rules = semantic_rules if tolerance == "semantic" else strict_rules
    return rules[color]()


def _entity_key(item):
    return getattr(item, "track_id", None) or item.id


def visual_color_fraction(inputs, params, services, node_id):
    frames_by_index = {}
    for frame in inputs["frames"].items:
        frames_by_index.setdefault(frame.frame_index, frame)
    rx0, ry0, rx1, ry1 = params["subject_region"]
    output = []
    for item in inputs["objects"].items:
        frame = frames_by_index.get(item.frame_index)
        if frame is None:
            output.append(TimedValue(_entity_key(item), item.timestamp, False, item.frame_index))
            continue
        x0, y0, x1, y1 = item.bbox
        sx0 = x0 + rx0 * (x1 - x0)
        sy0 = y0 + ry0 * (y1 - y0)
        sx1 = x0 + rx1 * (x1 - x0)
        sy1 = y0 + ry1 * (y1 - y0)
        width, height = frame.image.size
        crop = frame.image.convert("RGB").crop((
            max(0, int(sx0 * width)),
            max(0, int(sy0 * height)),
            min(width, max(1, int(sx1 * width))),
            min(height, max(1, int(sy1 * height))),
        )).convert("HSV")
        pixels = list(crop.getdata())
        tolerance = params.get("color_tolerance", "strict")
        fraction = (
            sum(
                _matches_color(h, s, v, params["color"], tolerance=tolerance)
                for h, s, v in pixels
            ) / len(pixels)
            if pixels else 0.0
        )
        matched = fraction >= float(params["min_fraction"])
        if matched and params.get("selection_mode", "fraction") == "dominant":
            other_fractions = [
                sum(
                    _matches_color(h, s, v, color, tolerance=tolerance)
                    for h, s, v in pixels
                ) / len(pixels)
                for color in (
                    "black", "white", "gray", "red", "orange", "yellow",
                    "green", "cyan", "blue", "purple", "pink", "brown",
                )
                if color != params["color"]
            ]
            matched = fraction >= max(other_fractions, default=0.0) + float(
                params.get("dominance_margin", 0.0)
            )
        output.append(TimedValue(
            _entity_key(item), item.timestamp,
            matched, item.frame_index,
        ))
    return ConditionSet(output)


def visual_geometry(inputs, params, services, node_id):
    output = []
    dimension = params["dimension"]
    value = params["value"]
    items = inputs["objects"].items
    if dimension == "aspect_ratio" and any(
        hasattr(item, "history") for item in items
    ):
        threshold = float(params.get("aspect_ratio_threshold", 1.0))
        for track in items:
            for observation in track.history:
                x0, y0, x1, y1 = observation.bbox
                width = max(0.0, x1 - x0)
                height = max(0.0, y1 - y0)
                source_width, source_height = observation.original_size
                ratio = (
                    (width * source_width) / (height * source_height)
                    if height and source_height else 0.0
                )
                if value == "horizontal":
                    matched = ratio >= threshold
                elif value == "vertical":
                    matched = ratio <= 1.0 / threshold
                else:
                    raise ValueError(f"unsupported aspect-ratio value: {value}")
                output.append(TimedValue(
                    track.id,
                    observation.timestamp,
                    matched,
                    observation.frame_index,
                ))
        return ConditionSet(output)
    relative_size_labels = {}
    if dimension == "size" and params.get("size_mode", "absolute") == "relative" and len(items) > 1:
        ranked = sorted(
            items,
            key=lambda item: max(0.0, item.bbox[2] - item.bbox[0])
            * max(0.0, item.bbox[3] - item.bbox[1]),
        )
        last = len(ranked) - 1
        for rank, item in enumerate(ranked):
            percentile = rank / last
            relative_size_labels[_entity_key(item)] = (
                "small" if percentile < 1 / 3
                else "large" if percentile > 2 / 3
                else "medium"
            )
    for item in items:
        x0, y0, x1, y1 = item.bbox
        if dimension == "size":
            area = max(0.0, x1 - x0) * max(0.0, y1 - y0)
            if relative_size_labels:
                matched = relative_size_labels[_entity_key(item)] == value
            elif value == "small":
                matched = area <= float(params["small_max_area"])
            elif value == "large":
                matched = area >= float(params["large_min_area"])
            else:
                matched = float(params["small_max_area"]) < area < float(params["large_min_area"])
        elif dimension == "position":
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            margin = float(params["position_margin"])
            positions = {
                "left": cx < margin, "center": margin <= cx <= 1.0 - margin,
                "right": cx > 1.0 - margin, "top": cy < margin,
                "middle": margin <= cy <= 1.0 - margin, "bottom": cy > 1.0 - margin,
            }
            matched = positions[value]
        elif dimension == "aspect_ratio":
            width = max(0.0, x1 - x0)
            height = max(0.0, y1 - y0)
            source_width, source_height = item.original_size
            ratio = (
                (width * source_width) / (height * source_height)
                if height and source_height else 0.0
            )
            threshold = float(params.get("aspect_ratio_threshold", 1.0))
            if value == "horizontal":
                matched = ratio >= threshold
            elif value == "vertical":
                matched = ratio <= 1.0 / threshold
            else:
                raise ValueError(f"unsupported aspect-ratio value: {value}")
        else:
            raise ValueError(f"unsupported geometry dimension: {dimension}")
        output.append(TimedValue(_entity_key(item), item.timestamp, matched, item.frame_index))
    return ConditionSet(output)


__all__ = ["visual_color_fraction", "visual_geometry"]
