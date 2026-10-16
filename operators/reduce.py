from __future__ import annotations

import statistics

from core.context import ConditionSet, ScalarSet, ScopedSet, TimedValue

from .condition_identity import entity_identity, merge_condition_metadata


def reduce_count(inputs, params, services, node_id):
    source = inputs["sets"]
    if isinstance(source, ScopedSet):
        return ScalarSet([
            TimedValue(group.scope_id, 0.0, len(group.items), None, {
                "scope_type": group.scope_type,
                "display_name": group.display_name,
            })
            for group in source.items
        ])
    grouped = {}
    for item in source.items:
        frame_index = getattr(item, "frame_index", None)
        timestamp = getattr(item, "timestamp", 0.0)
        if hasattr(item, "history"):
            for sample in item.history:
                grouped.setdefault((sample.frame_index, sample.timestamp), set()).add(item.id)
        else:
            grouped.setdefault((frame_index, timestamp), set()).add(
                getattr(item, "id", getattr(item, "subject_id", id(item)))
            )
    return ScalarSet([
        TimedValue("global", timestamp, len(values), frame_index)
        for (frame_index, timestamp), values in sorted(grouped.items(), key=lambda row: (row[0][1], row[0][0] or -1))
    ])


def reduce_exists(inputs, params, services, node_id):
    source = inputs["sets"]
    if isinstance(source, ScopedSet):
        return ConditionSet([
            TimedValue(group.scope_id, 0.0, bool(group.items), None, {
                "scope_type": group.scope_type,
                "display_name": group.display_name,
            })
            for group in source.items
        ])
    if params.get("scope", "global") == "entity":
        values = []
        for entity in source.items:
            history = getattr(entity, "history", None)
            if history is not None:
                values.extend(
                    TimedValue(entity.id, item.timestamp, True, item.frame_index, entity_identity(entity))
                    for item in history
                )
            else:
                values.append(TimedValue(
                    getattr(entity, "track_id", None) or getattr(entity, "id", None) or f"{entity.subject_id}|{entity.object_id}",
                    getattr(entity, "timestamp", 0.0),
                    True,
                    getattr(entity, "frame_index", None),
                    entity_identity(entity),
                ))
        return ConditionSet(values)
    count = reduce_count(inputs, params, services, node_id)
    return ConditionSet([
        TimedValue(item.key, item.timestamp, item.value > 0, item.frame_index, item.metadata)
        for item in count.items
    ])


def reduce_all(inputs, params, services, node_id):
    grouped = {}
    for item in inputs["conditions"].items:
        grouped.setdefault((item.frame_index, item.timestamp), []).append(bool(item.value))
    return ConditionSet([
        TimedValue("global", timestamp, all(values), frame_index)
        for (frame_index, timestamp), values in sorted(grouped.items(), key=lambda row: (row[0][1], row[0][0] or -1))
    ])


def reduce_statistic(inputs, params, services, node_id):
    grouped = {}
    for item in inputs["values"].items:
        grouped.setdefault((item.key, item.frame_index, item.timestamp), []).append(float(item.value))
    statistic_name = params["statistic"]
    functions = {
        "mean": statistics.mean,
        "median": statistics.median,
        "min": min,
        "max": max,
        "sum": sum,
    }
    if statistic_name not in functions:
        raise ValueError(f"unsupported statistic: {statistic_name}")
    return ScalarSet([
        TimedValue(key, timestamp, functions[statistic_name](values), frame_index)
        for (key, frame_index, timestamp), values in sorted(grouped.items())
    ])


def reduce_quantify(inputs, params, services, node_id):
    source = inputs["conditions"]
    mode = params["mode"]
    if isinstance(source, list):
        if mode == "for_each":
            return ConditionSet([
                item for condition_set in source for item in condition_set.items
            ])
        predicate = {
            "any": any,
            "all": all,
            "n_of_m": lambda values: sum(values) >= int(params.get("required_count", 1)),
        }.get(mode)
        if predicate is None:
            raise ValueError(f"unsupported quantifier: {mode}")
        combine_scope = params.get("combine_scope", "by_key")
        if combine_scope == "frame_any":
            frames = sorted({
                (item.frame_index, item.timestamp)
                for condition_set in source
                for item in condition_set.items
            })
            return ConditionSet([
                TimedValue(
                    "global",
                    timestamp,
                    predicate([
                        any(
                            bool(item.value)
                            for item in condition_set.items
                            if (item.frame_index, item.timestamp)
                            == (frame_index, timestamp)
                        )
                        for condition_set in source
                    ]),
                    frame_index,
                )
                for frame_index, timestamp in frames
            ])
        maps = [
            {
                (item.key, item.frame_index, item.timestamp): item
                for item in condition_set.items
            }
            for condition_set in source
        ]
        keys = sorted(set().union(*(mapping.keys() for mapping in maps)))
        return ConditionSet([
            TimedValue(
                key,
                timestamp,
                predicate([bool(mapping[(key, frame_index, timestamp)].value) if (key, frame_index, timestamp) in mapping else False for mapping in maps]),
                frame_index,
                merge_condition_metadata([mapping[(key, frame_index, timestamp)] for mapping in maps if (key, frame_index, timestamp) in mapping]),
            )
            for key, frame_index, timestamp in keys
        ])
    conditions = source.items
    if mode == "for_each":
        return ConditionSet(list(conditions))
    grouped = {}
    for item in conditions:
        grouped.setdefault((item.frame_index, item.timestamp), []).append(bool(item.value))
    required = int(params.get("required_count", 1))
    predicates = {
        "any": any,
        "all": all,
        "n_of_m": lambda values: sum(values) >= required,
    }
    if mode not in predicates:
        raise ValueError(f"unsupported quantifier: {mode}")
    return ConditionSet([
        TimedValue("global", timestamp, predicates[mode](values), frame_index)
        for (frame_index, timestamp), values in sorted(grouped.items(), key=lambda row: (row[0][1], row[0][0] or -1))
    ])


__all__ = [
    "reduce_all",
    "reduce_count",
    "reduce_exists",
    "reduce_quantify",
    "reduce_statistic",
]
