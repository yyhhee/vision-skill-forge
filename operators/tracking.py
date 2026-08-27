from __future__ import annotations

import math

from core.context import Track, TrackSet


def _iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0, ix1, iy1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - intersection
    return intersection / union if union else 0.0


def _center_pixels(item):
    x0, y0, x1, y1 = item.bbox
    width, height = item.original_size
    return ((x0 + x1) * width / 2.0, (y0 + y1) * height / 2.0)


def _predicted_bbox(track, candidate):
    """Project the last box to the candidate time using constant box motion."""

    if len(track.history) < 2:
        return track.history[-1].bbox
    previous, latest = track.history[-2:]
    elapsed = float(latest.timestamp) - float(previous.timestamp)
    lookahead = float(candidate.timestamp) - float(latest.timestamp)
    if elapsed <= 0 or lookahead <= 0:
        return latest.bbox
    ratio = min(2.0, lookahead / elapsed)
    projected = tuple(
        current + (current - prior) * ratio
        for prior, current in zip(previous.bbox, latest.bbox)
    )
    x0, y0, x1, y1 = projected
    return (
        max(0.0, min(1.0, x0)),
        max(0.0, min(1.0, y0)),
        max(0.0, min(1.0, x1)),
        max(0.0, min(1.0, y1)),
    )


def _motion_is_consistent(track, candidate, params):
    if not params.get("motion_consistency", False) or len(track.history) < 2:
        return True
    latest = track.history[-1]
    lx, ly = _center_pixels(latest)
    cx, cy = _center_pixels(candidate)
    new_dx, new_dy = cx - lx, cy - ly
    new_length = math.hypot(new_dx, new_dy)
    minimum = float(params.get("min_motion_pixels", 5.0))
    if new_length < minimum:
        return True

    # A single jittery or almost stationary sample must not erase an already
    # established trajectory direction.  Walk backwards to the nearest prior
    # observation with meaningful displacement instead of comparing only the
    # last two boxes.  This splits an identity switch into a new track while
    # still allowing slow sub-pixel motion.
    old_dx = old_dy = old_length = 0.0
    for previous in reversed(track.history[:-1]):
        px, py = _center_pixels(previous)
        old_dx, old_dy = lx - px, ly - py
        old_length = math.hypot(old_dx, old_dy)
        if old_length >= minimum:
            break
    if old_length < minimum:
        return True
    cosine = (old_dx * new_dx + old_dy * new_dy) / (old_length * new_length)
    return cosine >= float(params.get("min_direction_cosine", -1.0))


def track_iou(inputs, params, services, node_id):
    grouped = {}
    for obj in inputs["objects"].items:
        grouped.setdefault(obj.frame_index, []).append(obj)
    tracks = []
    next_id = 1
    last_seen = {}
    for sample_index, frame_index in enumerate(sorted(grouped)):
        frame_objects = grouped[frame_index]
        threshold = float(params["iou_threshold"])
        pairs = []
        for track_index, track in enumerate(tracks):
            if sample_index - last_seen[track_index] > int(params["max_missing_frames"]) + 1:
                continue
            for object_index, obj in enumerate(frame_objects):
                if params["same_label_only"] and track.label != obj.label:
                    continue
                score = _iou(track.history[-1].bbox, obj.bbox)
                if params.get("motion_prediction", False):
                    # Fast perspective motion can move and enlarge a vehicle
                    # enough that consecutive boxes no longer overlap at the
                    # configured threshold.  Compare against the projected box
                    # as well, while retaining the direction-consistency gate
                    # below to avoid switching to a nearby vehicle.
                    score = max(score, _iou(_predicted_bbox(track, obj), obj.bbox))
                if score < threshold or not _motion_is_consistent(track, obj, params):
                    continue
                pairs.append((score, track_index, object_index))

        # Resolve the frame as one deterministic one-to-one assignment.  The
        # previous implementation greedily iterated detector output order,
        # which could swap identities in dense traffic and invert direction.
        selected_tracks = set()
        selected_objects = set()
        assignment = {}
        for _score, track_index, object_index in sorted(
            pairs, key=lambda item: (-item[0], item[1], item[2])
        ):
            if track_index in selected_tracks or object_index in selected_objects:
                continue
            selected_tracks.add(track_index)
            selected_objects.add(object_index)
            assignment[object_index] = track_index

        for object_index, obj in enumerate(frame_objects):
            selected = assignment.get(object_index)
            if selected is not None:
                track = tracks[selected]
                obj.track_id = track.id
                track.history.append(obj)
                last_seen[selected] = sample_index
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
