from __future__ import annotations

from copy import deepcopy

from core.context import ObjectSet


def iter_object_samples(entity_set):
    """Yield concrete detection samples from ObjectSet or TrackSet inputs.

    Operators whose declared output is ObjectSet must never place Track objects
    inside that wrapper.  EntitySet inputs are intentionally generic, so a
    TrackSet is projected to its VisualObject history before object-level
    filtering, merging, relabelling, deduplication, or region membership.
    """

    for entity in entity_set.items:
        history = getattr(entity, "history", None)
        if history is None:
            yield entity
        else:
            yield from history


def objects_merge(inputs, params, services, node_id):
    """Merge explicit ObjectSet branches without hidden category competition."""

    merged = []
    for entity_set in inputs["objects"]:
        merged.extend(deepcopy(list(iter_object_samples(entity_set))))
    return ObjectSet(merged)


def objects_from_tracks(inputs, params, services, node_id):
    selection = params["selection"]
    items = []
    for track in inputs["tracks"].items:
        history = sorted(track.history, key=lambda item: (item.frame_index, item.timestamp))
        if selection == "first":
            selected = history[:1]
        elif selection == "latest":
            selected = history[-1:]
        elif selection == "all":
            selected = history
        else:
            raise ValueError(f"unsupported track box selection: {selection}")
        items.extend(deepcopy(selected))
    return ObjectSet(items)


def objects_relabel(inputs, params, services, node_id):
    items = deepcopy(list(iter_object_samples(inputs["objects"])))
    for item in items:
        item.label = params["label"]
    return ObjectSet(items)


__all__ = [
    "iter_object_samples",
    "objects_from_tracks",
    "objects_merge",
    "objects_relabel",
]
