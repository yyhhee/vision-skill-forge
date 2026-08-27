from __future__ import annotations

from copy import deepcopy

from core.context import Region, RegionSet, VectorSet, TimedValue
from .objects import iter_object_samples


def _validate_points(points):
    converted = [tuple(map(float, point)) for point in points]
    if len(converted) < 2 or any(len(point) != 2 for point in converted):
        raise ValueError("region points must contain coordinate pairs")
    if any(not (0.0 <= value <= 1.0) for point in converted for value in point):
        raise ValueError("region coordinates must be normalized to [0,1]")
    return converted


def region_manual(inputs, params, services, node_id):
    points = _validate_points(params["points"])
    if params["shape"] == "rectangle":
        if len(points) != 2:
            raise ValueError("rectangle requires exactly two corner points")
        (x0, y0), (x1, y1) = points
        points = [(min(x0, x1), min(y0, y1)), (max(x0, x1), min(y0, y1)),
                  (max(x0, x1), max(y0, y1)), (min(x0, x1), max(y0, y1))]
    elif len(points) < 3:
        raise ValueError("polygon requires at least three points")
    return RegionSet([Region(node_id, points)])


def region_manual_set(inputs, params, services, node_id):
    regions = []
    for item in params["regions"]:
        points = _validate_points(item["points"])
        shape = item.get("shape", "polygon")
        if shape == "rectangle":
            if len(points) != 2:
                raise ValueError("rectangle requires exactly two corner points")
            (x0, y0), (x1, y1) = points
            points = [
                (min(x0, x1), min(y0, y1)),
                (max(x0, x1), min(y0, y1)),
                (max(x0, x1), max(y0, y1)),
                (min(x0, x1), max(y0, y1)),
            ]
        elif len(points) < 3:
            raise ValueError("polygon requires at least three points")
        regions.append(Region(item["id"], points, item.get("label") or item["id"]))
    return RegionSet(regions)


def region_full_frame(inputs, params, services, node_id):
    return RegionSet([Region(node_id, [(0, 0), (1, 0), (1, 1), (0, 1)], "full frame")])


def region_from_objects(inputs, params, services, node_id):
    boxes = [item.bbox for item in iter_object_samples(inputs["objects"])]
    if not boxes:
        return RegionSet([])
    if params["mode"] == "largest":
        boxes = [max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))]
    elif params["mode"] == "union":
        boxes = [(min(b[0] for b in boxes), min(b[1] for b in boxes),
                  max(b[2] for b in boxes), max(b[3] for b in boxes))]
    regions = []
    for index, (x0, y0, x1, y1) in enumerate(boxes, 1):
        regions.append(Region(f"{node_id}_{index}", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]))
    return RegionSet(regions)


def regions_merge(inputs, params, services, node_id):
    """Combine explicitly configured RegionSets without changing region identity."""

    merged = []
    for region_set in inputs["regions"]:
        merged.extend(deepcopy(region_set.items))
    return RegionSet(merged)


def direction_manual(inputs, params, services, node_id):
    x, y = map(float, params["vector"])
    length = (x * x + y * y) ** 0.5
    if not length:
        raise ValueError("direction vector cannot be zero")
    metadata = {"source": "manual"}
    if params.get("start") is not None and params.get("end") is not None:
        metadata.update({"start": list(params["start"]), "end": list(params["end"])})
    return VectorSet([
        TimedValue(
            "global", 0.0, (x / length, y / length), None, metadata=metadata
        )
    ])


def direction_manual_set(inputs, params, services, node_id):
    values = []
    for item in params["directions"]:
        x, y = map(float, item["vector"])
        length = (x * x + y * y) ** 0.5
        if not length:
            raise ValueError("direction vector cannot be zero")
        metadata = {"source": "manual"}
        if item.get("start") is not None and item.get("end") is not None:
            metadata.update({
                "start": list(item["start"]),
                "end": list(item["end"]),
            })
        values.append(TimedValue(
            item["key"], 0.0, (x / length, y / length), None,
            metadata=metadata,
        ))
    return VectorSet(values)


def direction_image_axis(inputs, params, services, node_id):
    vectors = {
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
        "up": (0.0, -1.0),
        "down": (0.0, 1.0),
        "up_left": (-1.0, -1.0),
        "up_right": (1.0, -1.0),
        "down_left": (-1.0, 1.0),
        "down_right": (1.0, 1.0),
    }
    direction = params["direction"]
    if direction not in vectors:
        raise ValueError(f"unsupported image axis direction: {direction}")
    x, y = vectors[direction]
    length = (x * x + y * y) ** 0.5
    return VectorSet([
        TimedValue("global", 0.0, (x / length, y / length), None)
    ])
