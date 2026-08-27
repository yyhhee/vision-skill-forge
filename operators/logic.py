from __future__ import annotations

from core.context import ConditionSet, TimedValue
from .geometry import lane_for_track, majority_lane_for_track


def logic_compare(inputs, params, services, node_id):
    left = inputs["left"].items
    operator = params["operator"]
    output = []
    if operator in {"opposite_direction", "aligned_direction"}:
        right_by_frame = {item.frame_index: item for item in inputs["right"].items}
        broadcast = right_by_frame.get(None)
        threshold = float(params["threshold"])
        for item in left:
            reference = right_by_frame.get(item.frame_index, broadcast)
            if reference is None:
                continue
            cosine = item.value[0] * reference.value[0] + item.value[1] * reference.value[1]
            matched = (
                cosine < threshold
                if operator == "opposite_direction"
                else cosine > threshold
            )
            output.append(TimedValue(
                item.key, item.timestamp, matched, item.frame_index
            ))
    else:
        key_filter = params.get("key_filter")
        if key_filter is not None:
            allowed_keys = set(key_filter) if isinstance(key_filter, (list, tuple, set)) else {key_filter}
            left = [item for item in left if item.key in allowed_keys]
        right_items = inputs.get("right")
        right_by_key = {}
        if right_items is not None:
            right_by_key = {(item.key, item.frame_index): item.value for item in right_items.items}
        overrides = params.get("overrides", {})
        operator_overrides = params.get("operator_overrides", {})
        for item in left:
            other = right_by_key.get(
                (item.key, item.frame_index), overrides.get(item.key, params.get("value"))
            )
            predicates = {
                ">": lambda a, b: a > b,
                ">=": lambda a, b: a >= b,
                "<": lambda a, b: a < b,
                "<=": lambda a, b: a <= b,
                "==": lambda a, b: a == b,
                "!=": lambda a, b: a != b,
            }
            item_operator = operator_overrides.get(item.key, operator)
            if item_operator not in predicates or other is None:
                raise ValueError(f"unsupported comparison: {item_operator}")
            output.append(TimedValue(item.key, item.timestamp, predicates[item_operator](item.value, other), item.frame_index))
    return ConditionSet(output)


def _combine(condition_sets, predicate, combine_scope="by_key"):
    if combine_scope == "frame_any":
        frames = sorted({
            (item.frame_index, item.timestamp)
            for condition in condition_sets
            for item in condition.items
        })
        return ConditionSet([
            TimedValue(
                "global",
                timestamp,
                predicate([
                    any(
                        bool(item.value)
                        for item in condition.items
                        if (item.frame_index, item.timestamp) == (frame_index, timestamp)
                    )
                    for condition in condition_sets
                ]),
                frame_index,
            )
            for frame_index, timestamp in frames
        ])
    maps = [{(item.key, item.frame_index, item.timestamp): item for item in condition.items}
            for condition in condition_sets]
    keys = sorted(set().union(*(mapping.keys() for mapping in maps)))
    return ConditionSet([
        TimedValue(key[0], key[2], predicate([mapping.get(key) is not None and mapping[key].value for mapping in maps]), key[1])
        for key in keys
    ])


def logic_all(inputs, params, services, node_id):
    conditions = inputs["conditions"]
    if not isinstance(conditions, list):
        conditions = [conditions]
    return _combine(conditions, all, params.get("combine_scope", "by_key"))


def logic_any(inputs, params, services, node_id):
    conditions = inputs["conditions"]
    if not isinstance(conditions, list):
        conditions = [conditions]
    return _combine(conditions, any, params.get("combine_scope", "by_key"))


def logic_not(inputs, params, services, node_id):
    return ConditionSet([
        TimedValue(item.key, item.timestamp, not item.value, item.frame_index)
        for item in inputs["condition"].items
    ])


def logic_compare_heading_by_lane(inputs, params, services, node_id):
    tracks = {track.id: track for track in inputs["tracks"].items}
    regions = inputs["lanes"].items
    references = {item.key: item.value for item in inputs["references"].items}
    default_threshold = float(params["threshold"])
    default_relation = params.get("relation", "opposite")
    scope_overrides = params.get("scope_overrides", {})
    membership_mode = params.get("membership_mode", "majority_center")
    fixed_lane_by_track = {
        track.id: (
            majority_lane_for_track(track, regions)
            if membership_mode == "majority_center"
            else lane_for_track(track, regions)
        )
        for track in tracks.values()
    }
    output = []
    for item in inputs["headings"].items:
        track = tracks.get(item.key)
        if track is None:
            continue
        lane = fixed_lane_by_track.get(track.id)
        if membership_mode == "sample_center":
            lane = lane_for_track(track, regions, item.frame_index)
        if lane is None:
            continue
        reference = references.get(lane.id, references.get("global"))
        if reference is None:
            continue
        lane_overrides = scope_overrides.get(lane.id, {})
        threshold = float(lane_overrides.get("threshold", default_threshold))
        relation = lane_overrides.get("relation", default_relation)
        cosine = item.value[0] * reference[0] + item.value[1] * reference[1]
        matched = cosine < threshold if relation == "opposite" else cosine > threshold
        output.append(TimedValue(
            item.key,
            item.timestamp,
            matched,
            item.frame_index,
            {"region_id": lane.id, "direction_cosine": cosine},
        ))
    return ConditionSet(output)
