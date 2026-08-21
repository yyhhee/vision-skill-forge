from __future__ import annotations

import statistics

from core.context import ConditionSet, Event, EventSet, TimedValue


def effective_gap_tolerance(
    items, configured: float, *, infer_when_zero: bool = False
) -> float:
    """Keep regular sampled frames contiguous when cadence is coarser than a legacy default."""

    tolerance = float(configured)
    if tolerance <= 0 and not infer_when_zero:
        return tolerance
    timestamps = sorted({float(item.timestamp) for item in items})
    deltas = [
        right - left
        for left, right in zip(timestamps, timestamps[1:])
        if right > left
    ]
    return max(tolerance, statistics.median(deltas)) if deltas else tolerance


def temporal_hold(inputs, params, services, node_id):
    """Causally hold a configured boolean value for each entity key."""

    seconds = float(params["seconds"])
    held_value = bool(params["value"])
    grouped = {}
    for item in inputs["condition"].items:
        grouped.setdefault(item.key, []).append(item)
    output = []
    for key, items in sorted(grouped.items()):
        last_match = None
        for item in sorted(
            items, key=lambda value: (value.timestamp, value.frame_index)
        ):
            if bool(item.value) == held_value:
                last_match = item.timestamp
            value = bool(item.value)
            if last_match is not None and item.timestamp - last_match <= seconds:
                value = held_value
            output.append(TimedValue(key, item.timestamp, value, item.frame_index))
    return ConditionSet(output)


def temporal_persist(inputs, params, services, node_id):
    grouped = {}
    for item in inputs["condition"].items:
        grouped.setdefault(item.key, []).append(item)
    seconds = float(params["seconds"])
    tolerance = float(params["gap_tolerance_seconds"])
    trigger_mode = params["trigger_mode"]
    events = []

    def append_qualified_run(key, start, run_items):
        """Emit the qualified portion of one contiguous true-condition run."""

        if start is None or not run_items:
            return
        if seconds <= 0:
            triggers = [run_items[0]] if trigger_mode == "once" else run_items
            for trigger in triggers:
                events.append(Event(
                    f"{node_id}_{key}_{len(events) + 1}",
                    "event",
                    key,
                    trigger.timestamp,
                    trigger.timestamp,
                    {
                        "qualification_start_time": start,
                        "trigger_time": trigger.timestamp,
                        "required_duration_seconds": seconds,
                    },
                ))
            return
        qualified = [
            item for item in run_items
            if item.timestamp - start >= seconds
        ]
        if not qualified:
            return
        triggers = [qualified[0]] if trigger_mode == "once" else qualified
        run_end = run_items[-1].timestamp
        for trigger in triggers:
            events.append(Event(
                f"{node_id}_{key}_{len(events) + 1}",
                "event",
                key,
                trigger.timestamp,
                run_end,
                {
                    "qualification_start_time": start,
                    "trigger_time": trigger.timestamp,
                    "required_duration_seconds": seconds,
                },
            ))

    for key, items in sorted(grouped.items()):
        items.sort(key=lambda item: (item.timestamp, item.frame_index))
        # An immediate once event has no user-facing duration to absorb the
        # sampling cadence. Treat regular samples as one run so a 1 FPS input
        # does not create one duplicate event per frame. Explicitly timed
        # rules retain their configured zero-tolerance semantics.
        effective_tolerance = effective_gap_tolerance(
            items,
            tolerance,
            infer_when_zero=seconds <= 0 and trigger_mode == "once",
        )
        start = None
        previous = None
        run_items = []
        for item in items:
            is_discontinuous = (
                previous is not None
                and item.timestamp - previous > effective_tolerance
            )
            if not item.value or is_discontinuous:
                append_qualified_run(key, start, run_items)
                start = None
                run_items = []
            if item.value:
                if start is None:
                    start = item.timestamp
                run_items.append(item)
            previous = item.timestamp
        append_qualified_run(key, start, run_items)
    return EventSet(events)


def temporal_sequence(inputs, params, services, node_id):
    event_sets = inputs["events"]
    if not isinstance(event_sets, list) or len(event_sets) < 2:
        raise ValueError("temporal.sequence requires at least two EventSet inputs")
    expected_steps = params["steps"]
    if len(expected_steps) != len(event_sets):
        raise ValueError("temporal.sequence steps must match EventSet inputs")
    max_gap = float(params["max_gap_seconds"])
    same_key = bool(params["same_key"])
    ordered = [
        sorted(event_set.items, key=lambda event: (event.start_time, event.id))
        for event_set in event_sets
    ]
    results = []

    def extend(path, step_index):
        if step_index == len(ordered):
            results.append(Event(
                f"{node_id}_{len(results) + 1}",
                " → ".join(expected_steps),
                path[0].entity_id if same_key else "global",
                path[0].start_time,
                path[-1].end_time,
                {"step_event_ids": [event.id for event in path]},
            ))
            return True
        previous = path[-1]
        for candidate in ordered[step_index]:
            if candidate.start_time < previous.end_time:
                continue
            if candidate.start_time - previous.end_time > max_gap:
                continue
            if same_key and candidate.entity_id != path[0].entity_id:
                continue
            if extend(path + [candidate], step_index + 1):
                return True
        return False

    for first in ordered[0]:
        extend([first], 1)
    return EventSet(results)
