from __future__ import annotations

import math

from copy import deepcopy

from core.context import ConditionSet, ObjectSet, TimedValue
from .objects import iter_object_samples


def _point_in_polygon(point, polygon):
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x0, y0 = previous
        x1, y1 = current
        if ((y0 > y) != (y1 > y)) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            inside = not inside
        previous = current
    return inside


def _region_bounds(region):
    return (min(p[0] for p in region.points), min(p[1] for p in region.points),
            max(p[0] for p in region.points), max(p[1] for p in region.points))


def _overlap_fraction(subject, other):
    ax0, ay0, ax1, ay1 = subject
    bx0, by0, bx1, by1 = other
    area = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    intersection = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    return intersection / area if area else 0.0


def _key(item):
    return getattr(item, "track_id", None) or item.id


def spatial_inside(inputs, params, services, node_id):
    regions = inputs["region"].items
    output = []
    expanded = []
    for entity in inputs["objects"].items:
        if hasattr(entity, "history"):
            expanded.extend((entity.id, item) for item in entity.history)
        else:
            expanded.append((_key(entity), entity))
    for entity_key, item in expanded:
        if params["mode"] == "center":
            x0, y0, x1, y1 = item.bbox
            center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            value = any(_point_in_polygon(center, region.points) for region in regions)
        else:
            value = any(_overlap_fraction(item.bbox, _region_bounds(region)) >= float(params["overlap_threshold"])
                        for region in regions)
        output.append(TimedValue(entity_key, item.timestamp, value, item.frame_index))
    return ConditionSet(output)


def objects_filter_by_regions(inputs, params, services, node_id):
    """Keep objects inside/outside the union of explicitly supplied regions.

    This is intentionally a projection/filtering atom instead of event logic:
    presets can use the same annotated business scope for counting, tracking and
    evidence drawing without hard-coding a number of regions.
    """

    regions = inputs["regions"].items
    if not regions and params.get("empty_regions") == "passthrough":
        return ObjectSet([
            deepcopy(item) for item in iter_object_samples(inputs["objects"])
        ])
    mode = params.get("membership_mode", "center")
    keep_inside = params.get("keep", "inside") == "inside"
    threshold = float(params.get("overlap_threshold", 0.1))
    output = []
    for item in iter_object_samples(inputs["objects"]):
        if mode == "center":
            x0, y0, x1, y1 = item.bbox
            center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
            inside = any(_point_in_polygon(center, region.points) for region in regions)
        elif mode == "overlap":
            inside = any(
                _overlap_fraction(item.bbox, _region_bounds(region)) >= threshold
                for region in regions
            )
        else:
            raise ValueError(f"unsupported region membership mode: {mode}")
        if inside == keep_inside:
            output.append(deepcopy(item))
    return ObjectSet(output)


def spatial_associate(inputs, params, services, node_id):
    objects = inputs["objects"].items
    subjects = []
    for entity in inputs["subjects"].items:
        subjects.extend(entity.history if hasattr(entity, "history") else [entity])
    output = []
    for subject in subjects:
        candidates = [item for item in objects if item.frame_index == subject.frame_index]
        if params.get("same_source_only", False):
            candidates = [
                item for item in candidates
                if item.source_entity_id == _key(subject)
            ]
        if params["relation"] == "source_entity":
            value = any(
                item.source_entity_id == _key(subject)
                for item in candidates
            )
        elif params["relation"] == "overlap":
            value = any(_overlap_fraction(subject.bbox, item.bbox) >= float(params["threshold"])
                        for item in candidates)
        elif params["relation"] == "inside":
            value = any(_overlap_fraction(subject.bbox, item.bbox) >= float(params["threshold"])
                        for item in candidates)
        elif params["relation"] == "contains":
            value = any(_overlap_fraction(item.bbox, subject.bbox) >= float(params["threshold"])
                        for item in candidates)
        elif params["relation"] == "mutual_match":
            threshold = float(params["threshold"])
            value = any(
                _overlap_fraction(subject.bbox, item.bbox) >= threshold
                and _overlap_fraction(item.bbox, subject.bbox) >= threshold
                for item in candidates
            )
        elif params["relation"] == "best_owner":
            value = False
            frame_subjects = [item for item in subjects if item.frame_index == subject.frame_index]
            for candidate in candidates:
                scores = [
                    (_overlap_fraction(candidate.bbox, item.bbox), index, item)
                    for index, item in enumerate(frame_subjects)
                ]
                best_score, _, owner = max(scores, default=(0.0, -1, None), key=lambda row: (row[0], -row[1]))
                if owner is subject and best_score >= float(params["threshold"]):
                    value = True
                    break
        elif params["relation"] == "near":
            sx0, sy0, sx1, sy1 = subject.bbox
            sc = ((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)
            value = False
            for item in candidates:
                x0, y0, x1, y1 = item.bbox
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                if math.dist(sc, center) <= float(params["threshold"]):
                    value = True
                    break
        elif params["relation"] == "center_in_subject_region":
            sx0, sy0, sx1, sy1 = subject.bbox
            rx0, ry0, rx1, ry1 = params["subject_region"]
            region = (
                sx0 + rx0 * (sx1 - sx0),
                sy0 + ry0 * (sy1 - sy0),
                sx0 + rx1 * (sx1 - sx0),
                sy0 + ry1 * (sy1 - sy0),
            )
            value = False
            for item in candidates:
                x0, y0, x1, y1 = item.bbox
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                if region[0] <= center[0] <= region[2] and region[1] <= center[1] <= region[3]:
                    value = True
                    break
        elif params["relation"] == "center_in_object_region":
            sx0, sy0, sx1, sy1 = subject.bbox
            subject_center = ((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)
            rx0, ry0, rx1, ry1 = params["object_region"]
            value = False
            for item in candidates:
                x0, y0, x1, y1 = item.bbox
                region = (
                    x0 + rx0 * (x1 - x0),
                    y0 + ry0 * (y1 - y0),
                    x0 + rx1 * (x1 - x0),
                    y0 + ry1 * (y1 - y0),
                )
                if (
                    region[0] <= subject_center[0] <= region[2]
                    and region[1] <= subject_center[1] <= region[3]
                ):
                    value = True
                    break
        elif params["relation"] in {"left_of", "right_of", "above", "below"}:
            sx0, sy0, sx1, sy1 = subject.bbox
            sc = ((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)
            value = False
            for item in candidates:
                x0, y0, x1, y1 = item.bbox
                center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                relations = {
                    "left_of": sc[0] < center[0], "right_of": sc[0] > center[0],
                    "above": sc[1] < center[1], "below": sc[1] > center[1],
                }
                if relations[params["relation"]]:
                    value = True
                    break
        else:
            raise ValueError(f"unsupported association relation: {params['relation']}")
        output.append(TimedValue(_key(subject), subject.timestamp, value, subject.frame_index))
    return ConditionSet(output)
