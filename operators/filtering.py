from __future__ import annotations

from copy import deepcopy

from core.context import ObjectSet, TrackSet


def objects_filter_by_phrase(inputs, params, services, node_id):
    """Partition objects by their explicit detector phrase."""

    phrases = set(params["phrases"])
    include = params["mode"] == "include"
    return ObjectSet([
        deepcopy(item)
        for item in inputs["objects"].items
        if (item.phrase in phrases) == include
    ])


def objects_filter_by_label(inputs, params, services, node_id):
    """Partition objects by their explicit output label.

    This is intentionally separate from detector-phrase filtering: a workflow
    may use multiple grounding phrases for one visible category, then make an
    explicit category-level decision later in the graph.
    """

    labels = set(params["labels"])
    include = params["mode"] == "include"
    return ObjectSet([
        deepcopy(item)
        for item in inputs["objects"].items
        if (item.label in labels) == include
    ])


def filter_apply(inputs, params, services, node_id):
    conditions = {(item.key, item.frame_index): bool(item.value) for item in inputs["condition"].items}
    entities = inputs["objects"]
    if isinstance(entities, ObjectSet):
        items = deepcopy([
            item for item in entities.items
            if conditions.get((item.track_id or item.id, item.frame_index), False)
        ])
        if params.get("output_label"):
            for item in items:
                item.label = params["output_label"]
        return ObjectSet(items)
    if isinstance(entities, TrackSet):
        items = [track for track in entities.items if any(
            conditions.get((track.id, obj.frame_index), False) for obj in track.history
        )]
        return TrackSet(items)
    raise TypeError("filter.apply supports ObjectSet or TrackSet")


def tracks_filter(inputs, params, services, node_id):
    conditions = {
        (item.key, item.frame_index): bool(item.value)
        for item in inputs["condition"].items
    }
    mode = params["history_mode"]
    tracks = []
    for track in inputs["tracks"].items:
        matching = [
            item
            for item in track.history
            if conditions.get((track.id, item.frame_index), False)
        ]
        if not matching:
            continue
        copied = deepcopy(track)
        if mode == "matching_samples":
            copied.history = deepcopy(matching)
        elif mode != "whole_track":
            raise ValueError(f"unsupported track filter history mode: {mode}")
        tracks.append(copied)
    return TrackSet(tracks)


def tracks_filter_by_events(inputs, params, services, node_id):
    events_by_entity = {}
    for event in inputs["events"].items:
        if event.entity_id == "global":
            continue
        events_by_entity.setdefault(event.entity_id, []).append(event)
    output = []
    for track in inputs["tracks"].items:
        events = events_by_entity.get(track.id, [])
        if not events:
            continue
        copied = deepcopy(track)
        if params["time_window"] == "event":
            copied.history = [
                deepcopy(item)
                for item in track.history
                if any(
                    event.start_time <= item.timestamp <= event.end_time
                    for event in events
                )
            ]
            if not copied.history:
                continue
        elif params["time_window"] != "whole_track":
            raise ValueError(
                f"unsupported event track time window: {params['time_window']}"
            )
        output.append(copied)
    return TrackSet(output)


__all__ = [
    "filter_apply",
    "objects_filter_by_label",
    "objects_filter_by_phrase",
    "tracks_filter",
    "tracks_filter_by_events",
]
