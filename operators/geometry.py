from __future__ import annotations


def point_in_polygon(point, polygon) -> bool:
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x0, y0 = previous
        x1, y1 = current
        if ((y0 > y) != (y1 > y)) and x < (
            (x1 - x0) * (y - y0) / (y1 - y0) + x0
        ):
            inside = not inside
        previous = current
    return inside


def object_center(item) -> tuple[float, float]:
    x0, y0, x1, y1 = item.bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def track_object_at(track, frame_index: int | None = None):
    history = sorted(track.history, key=lambda item: (item.frame_index, item.timestamp))
    if not history:
        return None
    if frame_index is None:
        return history[-1]
    exact = [item for item in history if item.frame_index == frame_index]
    if exact:
        return exact[-1]
    earlier = [item for item in history if item.frame_index <= frame_index]
    return earlier[-1] if earlier else history[0]


def lane_for_track(track, regions, frame_index: int | None = None):
    item = track_object_at(track, frame_index)
    if item is None:
        return None
    center = object_center(item)
    return next(
        (region for region in regions if point_in_polygon(center, region.points)),
        None,
    )


def majority_lane_for_track(track, regions):
    """Return the lane containing most observed centers; ties use latest."""

    votes = {}
    latest = {}
    for item in sorted(track.history, key=lambda value: (
        value.frame_index, value.timestamp
    )):
        center = object_center(item)
        lane = next(
            (
                region for region in regions
                if point_in_polygon(center, region.points)
            ),
            None,
        )
        if lane is None:
            continue
        votes[lane.id] = votes.get(lane.id, 0) + 1
        latest[lane.id] = (item.frame_index, item.timestamp)
    if not votes:
        return None
    selected = max(votes, key=lambda lane_id: (votes[lane_id], latest[lane_id]))
    return next(region for region in regions if region.id == selected)


__all__ = [
    "lane_for_track", "majority_lane_for_track", "object_center",
    "point_in_polygon", "track_object_at",
]
