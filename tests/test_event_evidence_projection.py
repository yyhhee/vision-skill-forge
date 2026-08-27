from __future__ import annotations

from core.runtime import _attach_runtime_event_evidence


def test_legacy_event_is_projected_with_matching_track_box_evidence():
    events = [{
        "id": "fall_1",
        "label": "人员摔倒",
        "entity_id": "track_1",
        "start_time": 2.0,
        "end_time": 3.0,
        "metadata": {},
    }]
    tracks = [{
        "id": "track_1",
        "history": [{
            "id": "person_2",
            "label": "人员",
            "track_id": "track_1",
            "frame_index": 20,
            "timestamp": 2.0,
            "bbox": [0.1, 0.2, 0.5, 0.9],
        }],
    }]

    _attach_runtime_event_evidence(events, [], tracks)

    assert events[0]["evidence_boxes"] == [{
        "entity_id": "person_2",
        "track_id": "track_1",
        "frame_index": 20,
        "timestamp": 2.0,
        "bbox": [0.1, 0.2, 0.5, 0.9],
        "label": "人员",
    }]
    assert events[0]["metadata"]["evidence"][0]["evidence_type"] == "target_box"


def test_global_event_projects_all_detection_boxes_from_trigger_frame():
    events = [{
        "id": "joint_alert_1",
        "label": "多区域联合告警",
        "entity_id": "global",
        "start_time": 0.0,
        "end_time": 0.0,
        "metadata": {},
    }]
    detections = [
        {
            "id": "person_1", "label": "人员", "track_id": None,
            "frame_index": 0, "timestamp": 0.0,
            "bbox": [0.1, 0.1, 0.3, 0.8],
        },
        {
            "id": "person_2", "label": "人员", "track_id": None,
            "frame_index": 0, "timestamp": 0.0,
            "bbox": [0.5, 0.1, 0.7, 0.8],
        },
    ]

    _attach_runtime_event_evidence(events, detections, [])

    assert [item["entity_id"] for item in events[0]["evidence_boxes"]] == [
        "person_1", "person_2"
    ]


def test_same_runtime_box_from_detection_and_track_is_only_attached_once():
    sample = {
        "id": "vehicle_1",
        "label": "车辆",
        "track_id": "track_1",
        "frame_index": 8,
        "timestamp": 4.0,
        "bbox": [0.1, 0.2, 0.3, 0.4],
    }
    events = [{
        "id": "wrong_way_1",
        "label": "逆行车辆",
        "entity_id": "track_1",
        "start_time": 4.0,
        "end_time": 4.0,
        "metadata": {},
    }]

    _attach_runtime_event_evidence(
        events,
        [dict(sample)],
        [{"id": "track_1", "history": [dict(sample)]}],
    )

    assert len(events[0]["metadata"]["evidence"]) == 1
    assert len(events[0]["evidence_boxes"]) == 1
