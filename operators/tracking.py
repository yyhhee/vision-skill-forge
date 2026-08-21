from __future__ import annotations

from core.context import Track, TrackSet


def _iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - intersection
    return intersection / union if union else 0.0


def track_iou(inputs, params, services, node_id):
    grouped = {}
    for obj in inputs["objects"].items:
        grouped.setdefault(obj.frame_index, []).append(obj)
    tracks = []
    next_id = 1
    last_seen = {}
    for sample_index, frame_index in enumerate(sorted(grouped)):
        available = set(range(len(tracks)))
        for obj in grouped[frame_index]:
            candidates = []
            for idx in available:
                track = tracks[idx]
                if params["same_label_only"] and track.label != obj.label:
                    continue
                if sample_index - last_seen[idx] > int(params["max_missing_frames"]) + 1:
                    continue
                candidates.append((_iou(track.history[-1].bbox, obj.bbox), idx))
            score, selected = max(candidates, default=(0.0, -1))
            if selected >= 0 and score >= float(params["iou_threshold"]):
                track = tracks[selected]
                obj.track_id = track.id
                track.history.append(obj)
                last_seen[selected] = sample_index
                available.remove(selected)
            else:
                track_id = f"track_{next_id}"
                next_id += 1
                obj.track_id = track_id
                tracks.append(Track(track_id, obj.label, [obj]))
                last_seen[len(tracks) - 1] = sample_index
    return TrackSet(tracks)


def track_confirm(inputs, params, services, node_id):
    """Keep tracks with explicit observation support and temporal span."""

    min_hits = int(params["min_hits"])
    min_span = float(params["min_span_seconds"])
    confirmed = []
    for track in inputs["tracks"].items:
        timestamps = [item.timestamp for item in track.history]
        span = max(timestamps) - min(timestamps) if timestamps else 0.0
        if len(track.history) >= min_hits and span >= min_span:
            confirmed.append(track)
    return TrackSet(confirmed)


__all__ = ["track_iou", "track_confirm"]
