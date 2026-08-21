from __future__ import annotations

from copy import deepcopy

from core.context import ObjectSet


def objects_merge(inputs, params, services, node_id):
    """Merge explicit ObjectSet branches without hidden category competition."""

    merged = []
    for object_set in inputs["objects"]:
        merged.extend(deepcopy(object_set.items))
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
    items = deepcopy(inputs["objects"].items)
    for item in items:
        item.label = params["label"]
    return ObjectSet(items)


__all__ = ["objects_from_tracks", "objects_merge", "objects_relabel"]
