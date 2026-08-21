from __future__ import annotations

from copy import deepcopy

from core.context import EventSet, EvidenceRef, EvidenceSet, ResultItemSet


def evidence_collect(inputs, params, services, node_id):
    evidence = []
    for source_name, source in inputs.items():
        if source is None:
            continue
        for index, item in enumerate(source.items):
            entity_id = getattr(item, "id", getattr(item, "target_id", None))
            pair_id = None
            if hasattr(item, "subject_id"):
                entity_id = item.subject_id
                pair_id = f"{item.subject_id}:{item.object_id}"
            evidence.append(
                EvidenceRef(
                    evidence_id=f"{node_id}:{source_name}:{index}",
                    source_node=source_name,
                    evidence_type=type(item).__name__,
                    entity_id=entity_id,
                    track_id=getattr(item, "track_id", None),
                    pair_id=pair_id,
                    region_id=getattr(item, "scope_id", None),
                    frame_index=getattr(item, "frame_index", None),
                    timestamp=getattr(item, "timestamp", None),
                    bbox=getattr(item, "bbox", None),
                    value=getattr(item, "value", getattr(item, "state", None)),
                    metadata={
                        "object_id": getattr(item, "object_id", None),
                        "metrics": getattr(item, "metrics", None),
                        **getattr(item, "metadata", {}),
                    },
                )
            )
    return EvidenceSet(evidence)


def event_attach_evidence(inputs, params, services, node_id):
    events = deepcopy(inputs["events"].items)
    explicit = inputs.get("evidence")
    sources = {
        name: value
        for name, value in inputs.items()
        if name not in {"events", "evidence"} and value is not None
    }
    for event in events:
        evidence = list(event.metadata.get("evidence", []))
        if explicit is not None:
            evidence.extend(
                vars(item)
                for item in explicit.items
                if event.entity_id == "global"
                or event.entity_id in {item.entity_id, item.track_id}
            )
        for name, source in sources.items():
            for item in source.items:
                entity_id = getattr(item, "id", getattr(item, "key", None))
                track_id = getattr(item, "track_id", None)
                if hasattr(item, "history"):
                    entity_id = item.id
                    track_id = item.id
                pair_subject = getattr(item, "subject_id", None)
                matches = event.entity_id == "global" or event.entity_id in {
                    entity_id, track_id, pair_subject
                }
                if not matches:
                    continue
                evidence.append({
                    "source": name,
                    "entity_id": entity_id,
                    "track_id": track_id,
                    "subject_id": pair_subject,
                    "object_id": getattr(item, "object_id", None),
                    "frame_index": getattr(item, "frame_index", None),
                    "timestamp": getattr(item, "timestamp", None),
                    "bbox": list(item.bbox) if hasattr(item, "bbox") else None,
                    "value": getattr(item, "value", None),
                })
        event.metadata["evidence"] = evidence
    return EventSet(events)


def result_project(inputs, params, services, node_id):
    items = []
    for name, source in inputs.items():
        if source is None:
            continue
        for item in source.items:
            if hasattr(item, "history"):
                for sample in item.history:
                    items.append({
                        "result_type": name,
                        "entity_id": item.id,
                        "track_id": item.id,
                        "frame_index": sample.frame_index,
                        "timestamp": sample.timestamp,
                        "bbox": list(sample.bbox),
                        "label": item.label,
                    })
            elif hasattr(item, "start_time"):
                items.append({
                    "result_type": name,
                    "event_id": item.id,
                    "entity_id": item.entity_id,
                    "label": item.label,
                    "start_time": item.start_time,
                    "end_time": item.end_time,
                    "evidence": item.metadata.get("evidence", []),
                })
            elif hasattr(item, "bbox"):
                items.append({
                    "result_type": name,
                    "entity_id": item.id,
                    "track_id": item.track_id,
                    "frame_index": item.frame_index,
                    "timestamp": item.timestamp,
                    "bbox": list(item.bbox),
                    "label": item.label,
                })
            else:
                items.append({
                    "result_type": name,
                    "key": getattr(item, "key", getattr(item, "scope_id", None)),
                    "frame_index": getattr(item, "frame_index", None),
                    "timestamp": getattr(item, "timestamp", None),
                    "value": getattr(item, "value", None),
                })
    return ResultItemSet(items)


__all__ = ["event_attach_evidence", "evidence_collect", "result_project"]
