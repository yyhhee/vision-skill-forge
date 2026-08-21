from __future__ import annotations

import math

from core.context import Pair, PairSet


def _identity(item):
    return getattr(item, "track_id", None) or item.id


def _expanded(entity_set):
    values = []
    for entity in entity_set.items:
        if hasattr(entity, "history"):
            values.extend((_identity(entity), item) for item in entity.history)
        else:
            values.append((_identity(entity), entity))
    return values


def pairs_build(inputs, params, services, node_id):
    subjects = _expanded(inputs["subjects"])
    objects = _expanded(inputs["objects"])
    pairs = []
    for subject_id, subject in subjects:
        for object_id, obj in objects:
            if subject.frame_index != obj.frame_index:
                continue
            if params.get("same_source_only") and obj.source_entity_id != subject_id:
                continue
            pairs.append(Pair(
                subject_id,
                object_id,
                subject.timestamp,
                subject.frame_index,
                metadata={"subject_bbox": subject.bbox, "object_bbox": obj.bbox},
            ))
    return PairSet(pairs)


def _areas(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    intersection = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(
        0.0, min(ay1, by1) - max(ay0, by0)
    )
    return area_a, area_b, intersection


def pairs_measure(inputs, params, services, node_id):
    output = []
    for pair in inputs["pairs"].items:
        subject_bbox = pair.metadata["subject_bbox"]
        object_bbox = pair.metadata["object_bbox"]
        area_a, area_b, intersection = _areas(subject_bbox, object_bbox)
        union = area_a + area_b - intersection
        sx0, sy0, sx1, sy1 = subject_bbox
        ox0, oy0, ox1, oy1 = object_bbox
        subject_center = ((sx0 + sx1) / 2.0, (sy0 + sy1) / 2.0)
        object_center = ((ox0 + ox1) / 2.0, (oy0 + oy1) / 2.0)
        metrics = {
            "iou": intersection / union if union else 0.0,
            "ios": intersection / min(area_a, area_b) if min(area_a, area_b) else 0.0,
            "subject_coverage": intersection / area_a if area_a else 0.0,
            "object_coverage": intersection / area_b if area_b else 0.0,
            "center_distance": math.dist(subject_center, object_center),
        }
        output.append(Pair(
            pair.subject_id,
            pair.object_id,
            pair.timestamp,
            pair.frame_index,
            metrics,
            dict(pair.metadata),
        ))
    return PairSet(output)


def pairs_filter(inputs, params, services, node_id):
    metric = params["metric"]
    operator = params["operator"]
    threshold = float(params["threshold"])
    predicates = {
        ">": lambda value: value > threshold,
        ">=": lambda value: value >= threshold,
        "<": lambda value: value < threshold,
        "<=": lambda value: value <= threshold,
    }
    if operator not in predicates:
        raise ValueError(f"unsupported pair comparison: {operator}")
    return PairSet([
        pair for pair in inputs["pairs"].items
        if metric in pair.metrics and predicates[operator](pair.metrics[metric])
    ])


__all__ = ["pairs_build", "pairs_filter", "pairs_measure"]
