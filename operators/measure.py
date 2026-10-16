from __future__ import annotations

import math
import statistics

from core.context import EventSet, ObjectSet, ScalarSet, TimedValue, TrackSet, VectorSet

from .geometry import (
    lane_for_track,
    majority_lane_for_track,
    object_center,
    point_in_polygon,
)


def _center_pixels(obj):
    x0, y0, x1, y1 = obj.bbox
    width, height = obj.original_size
    return ((x0 + x1) * width / 2.0, (y0 + y1) * height / 2.0)


def measure_heading(inputs, params, services, node_id):
    window = max(2, int(params["window_frames"]))
    minimum = float(params["min_displacement_pixels"])
    box_ratio = float(params.get("min_displacement_box_ratio", 0.0))
    values = []
    for track in inputs["tracks"].items:
        history = track.history
        for index in range(1, len(history)):
            earlier = history[max(0, index - window + 1)]
            current = history[index]
            x0, y0 = _center_pixels(earlier)
            x1, y1 = _center_pixels(current)
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            effective_minimum = minimum
            if box_ratio > 0:
                width, height = current.original_size
                bx0, by0, bx1, by1 = current.bbox
                box_diagonal = math.hypot(
                    (bx1 - bx0) * width, (by1 - by0) * height
                )
                # Far targets are physically small in the image.  Requiring the
                # same absolute displacement as a near target suppresses valid
                # headings, so cap the threshold by a fraction of box size.
                effective_minimum = min(
                    minimum, max(2.0, box_diagonal * box_ratio)
                )
            if length >= effective_minimum:
                values.append(
                    TimedValue(track.id, current.timestamp, (dx / length, dy / length), current.frame_index, {"track_id": track.id, "object_id": track.id})
                )
    return VectorSet(values)


def measure_majority_heading(inputs, params, services, node_id):
    if params.get("aggregation", "per_frame") == "global":
        by_track = {}
        for item in inputs["directions"].items:
            by_track.setdefault(item.key, []).append(item.value)
        track_directions = []
        for key in sorted(by_track):
            dx = sum(value[0] for value in by_track[key])
            dy = sum(value[1] for value in by_track[key])
            length = math.hypot(dx, dy)
            if length:
                track_directions.append((dx / length, dy / length))
        if len(track_directions) < int(params["minimum_tracks"]):
            return VectorSet([])
        dx = sum(value[0] for value in track_directions)
        dy = sum(value[1] for value in track_directions)
        length = math.hypot(dx, dy)
        if not length:
            return VectorSet([])
        return VectorSet([
            TimedValue("global", 0.0, (dx / length, dy / length), None)
        ])

    grouped = {}
    for item in inputs["directions"].items:
        grouped.setdefault((item.frame_index, item.timestamp), []).append(item)
    values = []
    minimum = int(params["minimum_tracks"])
    for (frame_index, timestamp), items in sorted(grouped.items()):
        if len(items) < minimum:
            continue
        dx = sum(item.value[0] for item in items)
        dy = sum(item.value[1] for item in items)
        length = math.hypot(dx, dy)
        if length:
            values.append(TimedValue("global", timestamp, (dx / length, dy / length), frame_index))
    return VectorSet(values)


def measure_lane_majority_heading(inputs, params, services, node_id):
    """Build one whole-video reference direction per named lane."""

    tracks = {track.id: track for track in inputs["tracks"].items}
    regions = inputs["lanes"].items
    mode = params.get("membership_mode", "majority_center")
    lane_by_track = {
        track.id: (
            majority_lane_for_track(track, regions)
            if mode == "majority_center"
            else lane_for_track(track, regions)
        )
        for track in tracks.values()
    }
    by_lane_track = {}
    for item in inputs["directions"].items:
        track = tracks.get(item.key)
        if track is None:
            continue
        lane = lane_by_track.get(track.id)
        if mode == "sample_center":
            lane = lane_for_track(track, regions, item.frame_index)
        if lane is None:
            continue
        by_lane_track.setdefault((lane.id, track.id), []).append(item.value)

    by_lane = {}
    for (lane_id, _track_id), values in by_lane_track.items():
        dx = sum(value[0] for value in values)
        dy = sum(value[1] for value in values)
        length = math.hypot(dx, dy)
        if length:
            by_lane.setdefault(lane_id, []).append((dx / length, dy / length))

    minimum = int(params["minimum_tracks"])
    output = []
    for lane in regions:
        directions = by_lane.get(lane.id, [])
        if len(directions) < minimum:
            continue
        dx = sum(value[0] for value in directions)
        dy = sum(value[1] for value in directions)
        length = math.hypot(dx, dy)
        if length:
            output.append(
                TimedValue(lane.id, 0.0, (dx / length, dy / length), None)
            )
    return VectorSet(output)


def measure_count(inputs, params, services, node_id):
    entities = inputs.get("entities", inputs.get("objects"))
    if entities is None:
        raise ValueError("count requires a countable entity set")
    scope = params.get("scope", "frame")
    group_by = params.get("group_by", "none")
    if group_by not in {"none", "label"}:
        raise ValueError("count group_by must be none or label")
    if scope == "unique":
        if not isinstance(entities, (ObjectSet, TrackSet, EventSet)):
            raise ValueError("unique count supports ObjectSet, TrackSet, or EventSet")
        keys_by_group = {}
        for item in entities.items:
            key = getattr(item, "track_id", None) or getattr(item, "id", None)
            if key is not None:
                label = getattr(item, "label", "unlabeled") if group_by == "label" else "global"
                keys_by_group.setdefault(label, set()).add(key)
        return ScalarSet([
            TimedValue(label, 0.0, len(keys), None)
            for label, keys in sorted(keys_by_group.items())
        ])
    if not isinstance(entities, ObjectSet):
        raise ValueError("frame count requires ObjectSet")
    grouped = {}
    for item in entities.items:
        label = item.label if group_by == "label" else "global"
        grouped.setdefault((item.frame_index, item.timestamp, label), 0)
        grouped[(item.frame_index, item.timestamp, label)] += 1
    return ScalarSet([
        TimedValue(label, timestamp, count, frame_index)
        for (frame_index, timestamp, label), count in sorted(grouped.items())
    ])


def measure_region_count(inputs, params, services, node_id):
    """Count object centers in every named region for every sampled frame."""

    objects = inputs["objects"].items
    regions = inputs["regions"].items
    frames = inputs["frames"].items
    grouped = {
        (region.id, frame.frame_index, frame.timestamp): 0
        for frame in frames
        for region in regions
    }
    for item in objects:
        center = object_center(item)
        for region in regions:
            if point_in_polygon(center, region.points):
                grouped[(region.id, item.frame_index, item.timestamp)] += 1
                break
    return ScalarSet([
        TimedValue(region_id, timestamp, count, frame_index, {"region_id": region_id, "scope_type": "region"})
        for (region_id, frame_index, timestamp), count in sorted(
            grouped.items(), key=lambda entry: (entry[0][1], entry[0][0])
        )
    ])


def measure_speed(inputs, params, services, node_id):
    if params["unit"] != "pixels_per_second":
        raise ValueError("demo speed unit is fixed to pixels_per_second")
    window = max(2, int(params["window_frames"]))
    values = []
    for track in inputs["tracks"].items:
        for index in range(1, len(track.history)):
            earlier = track.history[max(0, index - window + 1)]
            current = track.history[index]
            elapsed = current.timestamp - earlier.timestamp
            if elapsed <= 0:
                continue
            x0, y0 = _center_pixels(earlier)
            x1, y1 = _center_pixels(current)
            values.append(TimedValue(track.id, current.timestamp, math.hypot(x1 - x0, y1 - y0) / elapsed,
                                     current.frame_index, {"track_id": track.id, "object_id": track.id}))
    aggregation = params.get("aggregation", "per_track")
    if aggregation == "per_track":
        return ScalarSet(values)
    grouped = {}
    for item in values:
        grouped.setdefault((item.frame_index, item.timestamp), []).append(item.value)
    return ScalarSet([
        TimedValue(
            "global",
            timestamp,
            statistics.median(group) if aggregation == "global_median"
            else sum(group) / len(group),
            frame_index,
        )
        for (frame_index, timestamp), group in sorted(grouped.items())
    ])


def measure_region_speed(inputs, params, services, node_id):
    """Aggregate track speed per named region while preserving frame time."""

    raw = measure_speed(
        {"tracks": inputs["tracks"]},
        {
            "window_frames": params["window_frames"],
            "unit": params["unit"],
            "aggregation": "per_track",
        },
        services,
        node_id,
    )
    tracks = {track.id: track for track in inputs["tracks"].items}
    regions = inputs["regions"].items
    membership_mode = params.get("membership_mode", "sample_center")
    grouped = {}
    for item in raw.items:
        track = tracks.get(item.key)
        if track is None:
            continue
        region = (
            majority_lane_for_track(track, regions)
            if membership_mode == "majority_center"
            else lane_for_track(track, regions, item.frame_index)
        )
        if region is None:
            continue
        grouped.setdefault(
            (region.id, item.frame_index, item.timestamp), []
        ).append(item.value)
    aggregation = params.get("aggregation", "median")
    return ScalarSet([
        TimedValue(
            region_id,
            timestamp,
            statistics.median(values)
            if aggregation == "median"
            else sum(values) / len(values),
            frame_index,
            {"region_id": region_id, "scope_type": "region"},
        )
        for (region_id, frame_index, timestamp), values in sorted(
            grouped.items(), key=lambda entry: (entry[0][1], entry[0][0])
        )
    ])
