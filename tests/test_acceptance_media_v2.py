from __future__ import annotations

import json
from pathlib import Path

import cv2


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "acceptance_media" / "manifest_v2.json"


def test_v2_acceptance_manifest_is_traceable_and_videos_stay_demo_sized():
    data = json.loads(MANIFEST.read_text("utf-8"))

    assert data["schema_version"] == "2.0"
    assert data["assets"]
    assert all(len(item["sha256"]) == 64 for item in data["assets"])
    assert all(Path(item["path"]).is_file() for item in data["assets"])
    videos = [item for item in data["assets"] if item["media_type"] == "video"]
    assert videos
    assert all(0 < item["duration_seconds"] <= 30 for item in videos)


def test_fall_fixture_contains_standing_transition_and_persistent_fallen_frames():
    path = ROOT / "data" / "acceptance_media" / "v2" / "P12_positive_transition.mp4"
    capture = cv2.VideoCapture(str(path))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    capture.release()

    assert fps == 2.0
    assert frame_count == 7
    assert frame_count / fps == 3.5


def test_acceptance_media_includes_all_temporal_control_sequences():
    directory = ROOT / "data" / "acceptance_media" / "v2"
    expected = {
        "P04_positive.mp4",
        "P05_positive_short.mp4",
        "shared_normal_highway_moving.mp4",
        "P06_positive.mp4",
        "P06_negative.mp4",
        "P07_positive.mp4",
        "P09_negative.mp4",
        "P09_confusion_helmet_in_hand.mp4",
        "P10_negative.mp4",
        "P10_confusion_unconnected.mp4",
        "P12_positive_transition.mp4",
        "P12_negative_standing.mp4",
        "P12_confusion_fall_without_persistence.mp4",
        "P13_negative.mp4",
        "P13_confusion_joints.mp4",
    }

    assert expected <= {path.name for path in directory.glob("*.mp4")}


def test_dwell_and_parking_fixtures_cross_the_ten_second_rule_boundary():
    """Positive and negative controls must both be long enough to exercise 10 s rules."""

    directory = ROOT / "data" / "acceptance_media" / "v2"
    for name in {
        "P06_positive.mp4",
        "P06_negative_long.mp4",
        "P06_confusion_outside_lane_long.mp4",
        "P07_positive.mp4",
        "P07_negative_moving_long.mp4",
        "P07_confusion_vehicle_outside_roi_long.mp4",
    }:
        capture = cv2.VideoCapture(str(directory / name))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        capture.release()

        assert fps == 2.0, name
        assert 10.0 < frame_count / fps <= 30.0, name
