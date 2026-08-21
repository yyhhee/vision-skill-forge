from __future__ import annotations

from core.context import ObjectSet, VisualObject


def _iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    intersection = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - intersection
    return intersection / union if union else 0.0


def _ios(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    intersection = max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))
    smaller = min((ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0))
    return intersection / smaller if smaller else 0.0


def _deduplicate(objects, threshold, metric):
    overlap = _ios if metric == "ios" else _iou
    kept = []
    for candidate in objects:
        if any(
            item.frame_index == candidate.frame_index
            and item.label == candidate.label
            and item.source_entity_id == candidate.source_entity_id
            and overlap(item.bbox, candidate.bbox) >= threshold
            for item in kept
        ):
            continue
        kept.append(candidate)
    return kept


def rex_ground(inputs, params, services, node_id):
    frames = inputs["frames"]
    targets = params["targets"]
    phrase_to_label = {
        phrase: target["label"]
        for target in targets
        for phrase in target["phrases"]
    }
    phrases = list(phrase_to_label)
    query_prompt = params.get("query_prompt")
    query_kwargs = (
        {"query_prompt": query_prompt.strip()}
        if isinstance(query_prompt, str) and query_prompt.strip()
        else {}
    )
    objects = []
    sequence = 0
    for frame in frames.items:
        detections = services.rex.detect(frame.image, phrases, **query_kwargs)
        for detection in detections:
            phrase = detection["phrase"]
            bbox = frame.to_original_bbox(tuple(detection["bbox"]))
            sequence += 1
            objects.append(
                VisualObject(
                    id=f"frame_{frame.frame_index}_{node_id}_{sequence}",
                    label=phrase_to_label.get(phrase, phrase),
                    phrase=phrase,
                    bbox=bbox,
                    frame_index=frame.frame_index,
                    timestamp=frame.timestamp,
                    source_node=node_id,
                    source_entity_id=frame.source_entity_id,
                    raw_output=detection.get("raw_output"),
                    original_size=frame.original_size,
                )
            )
    return ObjectSet(_deduplicate(
        objects,
        float(params["deduplicate_iou"]),
        params["deduplicate_metric"],
    ))


def rex_ground_raw(inputs, params, services, node_id):
    frames = inputs["frames"]
    targets = params["targets"]
    phrase_to_label = {
        phrase: target["label"]
        for target in targets
        for phrase in target["phrases"]
    }
    phrases = list(phrase_to_label)
    query_prompt = params.get("query_prompt")
    query_kwargs = (
        {"query_prompt": query_prompt.strip()}
        if isinstance(query_prompt, str) and query_prompt.strip()
        else {}
    )
    objects = []
    sequence = 0
    for frame in frames.items:
        for detection in services.rex.detect(frame.image, phrases, **query_kwargs):
            phrase = detection["phrase"]
            sequence += 1
            objects.append(VisualObject(
                id=f"frame_{frame.frame_index}_{node_id}_{sequence}",
                label=phrase_to_label.get(phrase, phrase),
                phrase=phrase,
                bbox=frame.to_original_bbox(tuple(detection["bbox"])),
                frame_index=frame.frame_index,
                timestamp=frame.timestamp,
                source_node=node_id,
                source_entity_id=frame.source_entity_id,
                raw_output=detection.get("raw_output"),
                original_size=frame.original_size,
            ))
    return ObjectSet(objects)


def objects_deduplicate(inputs, params, services, node_id):
    if params.get("keep") != "first":
        raise ValueError("objects.deduplicate currently supports keep=first only")
    return ObjectSet(_deduplicate(
        inputs["objects"].items,
        float(params["threshold"]),
        params["metric"],
    ))
