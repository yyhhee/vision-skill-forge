from __future__ import annotations

from copy import deepcopy

from core.context import (
    ObjectSet,
    PairSet,
    ScopedGroup,
    ScopedSet,
    TrackSet,
)
from .geometry import majority_lane_for_track, object_center, point_in_polygon


def _entity_id(item):
    return getattr(item, "track_id", None) or item.id


def _copy_set(source, items):
    if isinstance(source, ObjectSet):
        return ObjectSet(deepcopy(items))
    if isinstance(source, TrackSet):
        return TrackSet(deepcopy(items))
    raise TypeError("set operation supports ObjectSet or TrackSet")


def set_partition(inputs, params, services, node_id):
    entities = inputs["entities"]
    mode = params["mode"]
    groups = {}
    labels = {}
    if mode == "global":
        return ScopedSet([ScopedGroup("global", "global", "全部", deepcopy(entities.items))])
    if mode == "label":
        for item in entities.items:
            key = item.label
            groups.setdefault(key, []).append(deepcopy(item))
            labels[key] = key
        return ScopedSet([
            ScopedGroup("label", key, labels[key], groups[key]) for key in sorted(groups)
        ])
    if mode != "region":
        raise ValueError(f"unsupported partition mode: {mode}")
    regions = inputs.get("regions")
    if regions is None:
        raise ValueError("region partition requires regions")
    for region in regions.items:
        groups[region.id] = []
        labels[region.id] = region.label
    for item in entities.items:
        region = None
        if hasattr(item, "history"):
            region = majority_lane_for_track(item, regions.items)
        else:
            center = object_center(item)
            region = next(
                (candidate for candidate in regions.items if point_in_polygon(center, candidate.points)),
                None,
            )
        if region is not None:
            groups[region.id].append(deepcopy(item))
    return ScopedSet([
        ScopedGroup("region", key, labels[key], groups[key]) for key in sorted(groups)
    ])


def set_difference(inputs, params, services, node_id):
    left = inputs["left"]
    right = inputs["right"]
    field = params["field"]
    if field == "identity":
        excluded = {_entity_id(item) for item in right.items}
        kept = [item for item in left.items if _entity_id(item) not in excluded]
    else:
        excluded = {getattr(item, field) for item in right.items}
        kept = [item for item in left.items if getattr(item, field) not in excluded]
    return _copy_set(left, kept)


def _join(inputs, keep_matched):
    subjects = inputs["subjects"]
    matched = {pair.subject_id for pair in inputs["pairs"].items}
    items = [item for item in subjects.items if (_entity_id(item) in matched) == keep_matched]
    return _copy_set(subjects, items)


def set_semi_join(inputs, params, services, node_id):
    return _join(inputs, True)


def set_anti_join(inputs, params, services, node_id):
    return _join(inputs, False)


__all__ = ["set_anti_join", "set_difference", "set_partition", "set_semi_join"]
