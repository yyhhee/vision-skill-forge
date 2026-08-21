from __future__ import annotations

from copy import deepcopy
from itertools import combinations, pairwise, product

from core.context import Event, EventSet

from .temporal import temporal_persist


def temporal_qualify(inputs, params, services, node_id):
    mode = params["mode"]
    if mode in {"immediate", "continuous"}:
        seconds = 0.0 if mode == "immediate" else float(params["duration_seconds"])
        return temporal_persist(
            inputs,
            {
                "seconds": seconds,
                "gap_tolerance_seconds": float(params["allowed_gap_seconds"]),
                "trigger_mode": params["trigger_mode"],
            },
            services,
            node_id,
        )

    duration = float(params["duration_seconds"])
    window = float(params.get("window_seconds") or duration)
    required_ratio = float(params["required_ratio"])
    grouped = {}
    for item in inputs["condition"].items:
        grouped.setdefault(item.key, []).append(item)
    events = []
    for key, items in grouped.items():
        items.sort(key=lambda item: (item.timestamp, item.frame_index))
        for index, item in enumerate(items):
            start = item.timestamp - window
            selected = [candidate for candidate in items[: index + 1] if candidate.timestamp >= start]
            if not selected:
                continue
            deltas = [
                max(0.0, right.timestamp - left.timestamp)
                for left, right in pairwise(selected)
            ]
            cadence = sorted(deltas)[len(deltas) // 2] if deltas else 0.0
            true_duration = sum(
                delta for left, delta in zip(selected, deltas) if bool(left.value)
            ) + (cadence if bool(selected[-1].value) else 0.0)
            qualified = (
                true_duration >= duration
                if mode == "cumulative"
                else true_duration / max(window, 1e-9) >= required_ratio
            )
            if qualified:
                events.append(
                    Event(
                        f"{node_id}_{key}_{len(events) + 1}",
                        "event",
                        key,
                        selected[0].timestamp,
                        item.timestamp,
                        {
                            "qualification_mode": mode,
                            "true_duration_seconds": true_duration,
                            "window_seconds": window,
                            "required_ratio": required_ratio,
                        },
                    )
                )
                if params["trigger_mode"] == "once":
                    break
    return EventSet(events)


def temporal_event_duration(inputs, params, services, node_id):
    minimum = float(params["minimum_seconds"])
    return EventSet([
        Event(
            f"{node_id}_{index}",
            params["label"] or event.label,
            event.entity_id,
            event.start_time,
            event.end_time,
            {**event.metadata, "source_event_id": event.id},
        )
        for index, event in enumerate(inputs["events"].items, start=1)
        if event.end_time - event.start_time >= minimum
    ])


def _key(event, scope, fields):
    if scope == "global":
        return "global"
    if scope in {"object", "track", "pair", "region", "camera", "scene"}:
        return event.entity_id
    return tuple(event.metadata.get(field) for field in fields)


def _joined_event(node_id, index, selected, label, entity_id):
    return Event(
        f"{node_id}_{index}",
        label,
        entity_id,
        min(event.start_time for event in selected),
        max(event.end_time for event in selected),
        {
            "branch_event_ids": [event.id for event in selected],
            "branch_labels": [event.label for event in selected],
            "evidence": [
                evidence
                for event in selected
                for evidence in event.metadata.get("evidence", [])
            ],
        },
    )


def temporal_join(inputs, params, services, node_id):
    event_sets = inputs["events"]
    if not isinstance(event_sets, list) or not event_sets:
        raise ValueError("temporal.join requires one or more EventSet inputs")
    mode = params["mode"]
    required = int(params.get("required_count") or len(event_sets))
    if mode == "any":
        required = 1
    if mode != "n_of_m" and mode not in {"any"}:
        required = len(event_sets)
    if required < 1 or required > len(event_sets):
        raise ValueError("required_count must be within the number of branches")

    scope = params["correlation_scope"]
    fields = params.get("correlation_fields", [])
    max_matches = int(params["maximum_matches"])
    window = params.get("window_seconds")
    results = []
    for branch_indexes in combinations(range(len(event_sets)), required):
        branches = [event_sets[index].items for index in branch_indexes]
        if any(not branch for branch in branches):
            continue
        for selected in product(*branches):
            keys = [_key(event, scope, fields) for event in selected]
            if scope != "global" and len(set(keys)) != 1:
                continue
            if mode in {"all_active", "overlap"}:
                active_start = max(event.start_time for event in selected)
                active_end = min(event.end_time for event in selected)
                if active_start > active_end:
                    continue
            elif mode == "all_completed_within_window":
                if window is None:
                    raise ValueError("window_seconds is required for window join")
                if max(event.end_time for event in selected) - min(
                    event.start_time for event in selected
                ) > float(window):
                    continue
            results.append(
                _joined_event(
                    node_id,
                    len(results) + 1,
                    selected,
                    params["label"],
                    keys[0] if scope != "global" else "global",
                )
            )
            if len(results) >= max_matches:
                return EventSet(results)
    return EventSet(results)


def temporal_sequence_v2(inputs, params, services, node_id):
    event_sets = inputs["events"]
    if not isinstance(event_sets, list) or len(event_sets) < 2:
        raise ValueError("temporal.sequence@2.0 requires at least two branches")
    transitions = params.get("transitions", [])
    if transitions and len(transitions) != len(event_sets) - 1:
        raise ValueError("transitions must have one item between every two stages")
    if not transitions:
        transitions = [
            {"minimum_delay_seconds": 0.0, "maximum_delay_seconds": None}
            for _ in range(len(event_sets) - 1)
        ]
    scope = params["correlation_scope"]
    fields = params.get("correlation_fields", [])
    ordered = [sorted(item.items, key=lambda event: (event.start_time, event.id)) for item in event_sets]
    results = []

    def anchor(event, name):
        if name == "start":
            return event.start_time
        if name == "end":
            return event.end_time
        return float(event.metadata.get("trigger_time", event.end_time))

    def relation_delay(source, target, transition):
        relation = transition.get("relation", "after")
        source_time = anchor(source, transition.get("source_anchor", "end"))
        target_time = anchor(target, transition.get("target_anchor", "start"))
        if relation == "after":
            matched, delay = target_time >= source_time, target_time - source_time
        elif relation == "before":
            matched, delay = target_time <= source_time, source_time - target_time
        elif relation == "during":
            matched = target.start_time >= source.start_time and target.end_time <= source.end_time
            delay = abs(target_time - source_time)
        elif relation == "contains":
            matched = target.start_time <= source.start_time and target.end_time >= source.end_time
            delay = abs(target_time - source_time)
        elif relation == "overlaps":
            matched = max(source.start_time, target.start_time) <= min(source.end_time, target.end_time)
            delay = abs(target_time - source_time)
        elif relation == "until":
            matched = source.start_time <= target.start_time <= source.end_time
            delay = target.start_time - source.start_time
        else:
            raise ValueError(f"unsupported temporal relation: {relation}")
        return matched, delay

    def extend(path, stage_index):
        if stage_index == len(ordered):
            results.append(
                _joined_event(
                    node_id,
                    len(results) + 1,
                    path,
                    params["label"],
                    _key(path[0], scope, fields),
                )
            )
            return bool(params["consume_events"])
        previous = path[-1]
        transition = transitions[stage_index - 1]
        minimum = float(transition.get("minimum_delay_seconds", 0.0))
        maximum = transition.get("maximum_delay_seconds")
        for candidate in ordered[stage_index]:
            related, delay = relation_delay(previous, candidate, transition)
            if not related or delay < minimum or (maximum is not None and delay > float(maximum)):
                continue
            if scope != "global" and _key(candidate, scope, fields) != _key(path[0], scope, fields):
                continue
            if extend(path + [candidate], stage_index + 1):
                return True
        return False

    for event in ordered[0]:
        extend([event], 1)
    return EventSet(results)


def temporal_absence(inputs, params, services, node_id):
    anchors = inputs["anchors"].items
    forbidden = inputs["forbidden"].items
    before = float(params["before_seconds"])
    after = float(params["after_seconds"])
    same_key = bool(params["same_key"])
    results = []
    for anchor in anchors:
        found = any(
            (not same_key or item.entity_id == anchor.entity_id)
            and anchor.start_time - before <= item.start_time <= anchor.end_time + after
            for item in forbidden
        )
        if not found:
            results.append(
                _joined_event(
                    node_id, len(results) + 1, [anchor], params["label"], anchor.entity_id
                )
            )
    return EventSet(results)


def temporal_repeat(inputs, params, services, node_id):
    window = float(params["window_seconds"])
    minimum = int(params["minimum_count"])
    grouped = {}
    for event in inputs["events"].items:
        key = event.entity_id if params["same_key"] else "global"
        grouped.setdefault(key, []).append(event)
    results = []
    for key, events in grouped.items():
        events.sort(key=lambda event: (event.start_time, event.id))
        for index, event in enumerate(events):
            selected = [
                candidate
                for candidate in events[index:]
                if candidate.start_time - event.start_time <= window
            ][:minimum]
            if len(selected) >= minimum:
                results.append(
                    _joined_event(
                        node_id, len(results) + 1, selected, params["label"], key
                    )
                )
                break
    return EventSet(results)


def event_trigger(inputs, params, services, node_id):
    grouped = {}
    for event in sorted(inputs["events"].items, key=lambda item: (item.start_time, item.id)):
        key = event.entity_id if params["cooldown_scope"] == "entity" else "global"
        grouped.setdefault(key, []).append(event)
    emitted = []
    cooldown = float(params["cooldown_seconds"])
    for events in grouped.values():
        last_time = None
        for event in events:
            if params["repeat_policy"] == "first_only" and last_time is not None:
                continue
            if last_time is not None and event.start_time - last_time < cooldown:
                continue
            copied = deepcopy(event)
            copied.id = f"{node_id}_{len(emitted) + 1}"
            copied.label = params["label"] or copied.label
            copied.metadata.update({
                "source_event_id": event.id,
                "severity": params["severity"],
                "notification_enabled": bool(params["notification_enabled"]),
            })
            emitted.append(copied)
            last_time = event.start_time
    return EventSet(emitted)


__all__ = [
    "event_trigger",
    "temporal_absence",
    "temporal_event_duration",
    "temporal_join",
    "temporal_qualify",
    "temporal_repeat",
    "temporal_sequence_v2",
]
