from __future__ import annotations

from core.context import ObjectSet, VisualObject
from .objects import iter_object_samples


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


def _instance_overlap(a, b, threshold):
    """Decide whether two same-class boxes are observations of one instance.

    Plain IoS incorrectly suppresses distinct, partially occluded instances:
    a smaller person's box can overlap much of itself with a nearer person's
    box even though their centres are clearly different.  Multi-view evidence
    is treated as the same instance when the boxes have ordinary NMS-level
    IoU, or when one box is nearly contained in the other *and* their centres
    are tightly aligned.
    """

    if _iou(a, b) >= threshold:
        return True
    if _ios(a, b) < max(0.8, threshold):
        return False
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    distance = ((ax0 + ax1 - bx0 - bx1) ** 2 + (ay0 + ay1 - by0 - by1) ** 2) ** 0.5 / 2.0
    smaller_diagonal = min(
        ((ax1 - ax0) ** 2 + (ay1 - ay0) ** 2) ** 0.5,
        ((bx1 - bx0) ** 2 + (by1 - by0) ** 2) ** 0.5,
    )
    return bool(smaller_diagonal and distance / smaller_diagonal <= 0.25)


def _deduplicate(objects, threshold, metric, keep="first"):
    overlap = _ios if metric == "ios" else _iou
    candidates = list(objects)
    if keep == "best_localization":
        # Stable sorting keeps source order when two observations have the same
        # localization quality.  Un-clipped tile detections can therefore
        # replace coarser full-frame detections without making output random.
        candidates.sort(
            key=lambda item: float(getattr(item, "localization_score", 1.0)),
            reverse=True,
        )
    kept = []
    for candidate in candidates:
        if any(
            item.frame_index == candidate.frame_index
            and item.label == candidate.label
            and item.source_entity_id == candidate.source_entity_id
            and (
                _instance_overlap(item.bbox, candidate.bbox, threshold)
                if metric == "instance"
                else overlap(item.bbox, candidate.bbox) >= threshold
            )
            for item in kept
        ):
            continue
        kept.append(candidate)
    return kept


def _localization_score(frame, bbox):
    """Prefer detailed tile observations unless the box is crop-clipped."""

    sx0, sy0, sx1, sy1 = frame.source_rect
    source_area = max((sx1 - sx0) * (sy1 - sy0), 1e-6)
    detail_gain = min(8.0, source_area ** -0.5)
    x0, y0, x1, y1 = bbox
    edge_epsilon = 0.015
    clipped = (
        (sx0 > edge_epsilon and x0 <= edge_epsilon)
        or (sy0 > edge_epsilon and y0 <= edge_epsilon)
        or (sx1 < 1.0 - edge_epsilon and x1 >= 1.0 - edge_epsilon)
        or (sy1 < 1.0 - edge_epsilon and y1 >= 1.0 - edge_epsilon)
    )
    return detail_gain * (0.25 if clipped else 1.0)


def rex_ground_raw(inputs, params, services, node_id):
    frames = inputs["frames"]
    targets = params["targets"]
    phrase_to_label = {
        phrase: target["label"]
        for target in targets
        for phrase in target["phrases"]
    }
    if params.get("phrase_selection", "all_phrases") == "primary_per_target":
        phrases = []
        seen = set()
        for target in targets:
            primary = next(
                (
                    phrase for phrase in target["phrases"]
                    if isinstance(phrase, str) and phrase.strip()
                ),
                None,
            )
            if primary and primary not in seen:
                phrases.append(primary)
                seen.add(primary)
    else:
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
            local_bbox = tuple(detection["bbox"])
            sequence += 1
            objects.append(VisualObject(
                id=f"frame_{frame.frame_index}_{node_id}_{sequence}",
                label=phrase_to_label.get(phrase, phrase),
                phrase=phrase,
                bbox=frame.to_original_bbox(local_bbox),
                frame_index=frame.frame_index,
                timestamp=frame.timestamp,
                source_node=node_id,
                source_entity_id=frame.source_entity_id,
                raw_output=detection.get("raw_output"),
                original_size=frame.original_size,
                localization_score=_localization_score(frame, local_bbox),
            ))
    return ObjectSet(objects)


def objects_deduplicate(inputs, params, services, node_id):
    keep = params.get("keep", "first")
    if keep not in {"first", "best_localization"}:
        raise ValueError(
            "objects.deduplicate keep must be first or best_localization"
        )
    metric = params["metric"]
    if metric not in {"ios", "iou", "instance"}:
        raise ValueError(
            "objects.deduplicate metric must be ios, iou or instance"
        )
    return ObjectSet(_deduplicate(
        iter_object_samples(inputs["objects"]),
        float(params["threshold"]),
        metric,
        keep,
    ))
