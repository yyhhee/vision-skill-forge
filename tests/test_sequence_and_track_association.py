from __future__ import annotations

from core.context import (
    Event,
    EventSet,
    ObjectSet,
    Track,
    TrackSet,
    VisualObject,
)
from operators.spatial import spatial_associate
from operators.temporal import temporal_sequence
from operators.tracking import track_iou


def _obj(object_id, bbox, frame_index, timestamp, track_id=None):
    return VisualObject(
        id=object_id,
        label="车辆",
        phrase="vehicle",
        bbox=bbox,
        frame_index=frame_index,
        timestamp=timestamp,
        source_node="test",
        track_id=track_id,
    )


def test_spatial_associate_expands_track_history_and_keys_conditions_by_track_id():
    track = Track(
        "track_1",
        "车辆",
        [
            _obj("a0", (0.1, 0.1, 0.3, 0.3), 0, 0.0, "track_1"),
            _obj("a1", (0.2, 0.1, 0.4, 0.3), 1, 1.0, "track_1"),
        ],
    )
    evidence = ObjectSet([
        _obj("e1", (0.22, 0.12, 0.38, 0.28), 1, 1.0),
    ])

    result = spatial_associate(
        {"subjects": TrackSet([track]), "objects": evidence},
        {"relation": "overlap", "threshold": 0.5, "subject_region": [0, 0, 1, 1]},
        None,
        "associate",
    )

    assert [(item.key, item.frame_index, item.value) for item in result.items] == [
        ("track_1", 0, False),
        ("track_1", 1, True),
    ]


def test_iou_tracking_uses_sample_order_not_original_video_frame_number():
    objects = ObjectSet([
        _obj("car_0", (0.10, 0.10, 0.30, 0.30), 0, 0.0),
        _obj("car_12", (0.11, 0.10, 0.31, 0.30), 12, 0.5),
        _obj("car_24", (0.12, 0.10, 0.32, 0.30), 24, 1.0),
    ])

    result = track_iou(
        {"objects": objects},
        {
            "iou_threshold": 0.3,
            "max_missing_frames": 0,
            "same_label_only": True,
        },
        None,
        "tracks",
    )

    assert len(result.items) == 1
    assert [item.frame_index for item in result.items[0].history] == [0, 12, 24]


def test_temporal_sequence_matches_order_gap_and_same_entity():
    steps = [
        EventSet([
            Event("enter_a", "进入", "track_a", 1.0, 1.0),
            Event("enter_b", "进入", "track_b", 2.0, 2.0),
        ]),
        EventSet([
            Event("leave_b", "离开", "track_b", 4.0, 4.0),
            Event("leave_a_late", "离开", "track_a", 9.0, 9.0),
        ]),
    ]

    result = temporal_sequence(
        {"events": steps},
        {"steps": ["进入", "离开"], "max_gap_seconds": 5.0, "same_key": True},
        None,
        "sequence",
    )

    assert [(event.entity_id, event.start_time, event.end_time) for event in result.items] == [
        ("track_b", 2.0, 4.0),
    ]
    assert result.items[0].metadata["step_event_ids"] == ["enter_b", "leave_b"]


def test_temporal_sequence_can_match_global_steps_when_same_key_is_false():
    result = temporal_sequence(
        {
            "events": [
                EventSet([Event("smoke", "烟雾", "camera", 1.0, 1.0)]),
                EventSet([Event("fire", "明火", "other", 3.0, 3.0)]),
            ]
        },
        {"steps": ["烟雾", "明火"], "max_gap_seconds": 3.0, "same_key": False},
        None,
        "sequence",
    )

    assert len(result.items) == 1
    assert result.items[0].entity_id == "global"
