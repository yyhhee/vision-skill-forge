from __future__ import annotations

from copy import deepcopy

from core.context import EventSet
from .temporal import temporal_persist


def event_from_condition(inputs, params, services, node_id):
    events = temporal_persist(inputs, params, services, node_id)
    for event in events.items:
        event.label = params["label"]
    return events


def event_relabel(inputs, params, services, node_id):
    items = deepcopy(inputs["events"].items)
    for item in items:
        item.label = params["label"]
    return EventSet(items)


__all__ = ["event_from_condition", "event_relabel"]
