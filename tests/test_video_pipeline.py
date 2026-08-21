import importlib
from pathlib import Path

import cv2
import numpy as np
import pytest

from core.registry import build_default_registry
from core.schema import VisualSkillSpec


def load_runtime_api():
    try:
        return importlib.import_module("core.executor"), importlib.import_module(
            "operators"
        )
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"video runtime is not implemented: {exc}")


def write_video(path: Path):
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"MJPG"), 2.0, (100, 60)
    )
    assert writer.isOpened()
    for index in range(4):
        frame = np.full((60, 100, 3), index * 20, dtype=np.uint8)
        writer.write(frame)
    writer.release()


class MovingVehiclesGateway:
    def __init__(self):
        self.index = 0

    def detect(self, image, phrases):
        step = self.index
        self.index += 1
        right = 0.02 * step
        left = -0.02 * step
        return [
            {
                "phrase": "vehicle",
                "bbox": [0.10 + right, 0.10, 0.25 + right, 0.30],
                "raw_output": "vehicle-a",
            },
            {
                "phrase": "vehicle",
                "bbox": [0.10 + right, 0.40, 0.25 + right, 0.60],
                "raw_output": "vehicle-b",
            },
            {
                "phrase": "vehicle",
                "bbox": [0.75 + left, 0.70, 0.90 + left, 0.90],
                "raw_output": "vehicle-c",
            },
        ]


def wrong_way_skill():
    return VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": "wrong_way",
            "display_name": "逆行检测",
            "original_instruction": "检测逆行超过1秒的车辆",
            "compile_status": "compiled",
            "input": {"accept": ["video"]},
            "nodes": [
                {
                    "id": "video",
                    "op": "media.video@1.0",
                    "inputs": {"media": "$input"},
                    "params": {},
                },
                {
                    "id": "frames",
                    "op": "video.sample@1.0",
                    "inputs": {"video": "$video"},
                    "params": {"mode": "fps", "fps": 2.0},
                },
                {
                    "id": "vehicles",
                    "op": "rex.ground@1.0",
                    "inputs": {"frames": "$frames"},
                    "params": {
                        "targets": [{"label": "车辆", "phrases": ["vehicle"]}]
                    },
                },
                {
                    "id": "tracks",
                    "op": "track.iou@1.0",
                    "inputs": {"objects": "$vehicles"},
                    "params": {"iou_threshold": 0.3, "max_missing_frames": 1},
                },
                {
                    "id": "headings",
                    "op": "measure.heading@1.0",
                    "inputs": {"tracks": "$tracks"},
                    "params": {
                        "window_frames": 2,
                        "min_displacement_pixels": 0.1,
                    },
                },
                {
                    "id": "majority",
                    "op": "measure.majority_heading@1.0",
                    "inputs": {"directions": "$headings"},
                    "params": {"minimum_tracks": 3},
                },
                {
                    "id": "opposite",
                    "op": "logic.compare@1.0",
                    "inputs": {"left": "$headings", "right": "$majority"},
                    "params": {
                        "operator": "opposite_direction",
                        "threshold": -0.5,
                    },
                },
                {
                    "id": "confirmed",
                    "op": "temporal.persist@1.0",
                    "inputs": {"condition": "$opposite"},
                    "params": {
                        "seconds": 1.0,
                        "scope": "track",
                        "gap_tolerance_seconds": 0.6,
                        "trigger_mode": "once",
                    },
                },
                {
                    "id": "alerts",
                    "op": "output.alert@1.0",
                    "inputs": {"events": "$confirmed"},
                    "params": {"label": "逆行车辆"},
                },
            ],
            "outputs": {"events": "$alerts"},
        }
    )


def test_video_pipeline_samples_tracks_and_emits_wrong_way_event(tmp_path):
    executor_module, operators_module = load_runtime_api()
    video_path = tmp_path / "moving.avi"
    write_video(video_path)
    services = executor_module.ExecutionServices(
        rex=MovingVehiclesGateway(), output_dir=tmp_path / "outputs"
    )
    engine = executor_module.ExecutionEngine(
        build_default_registry(),
        operators_module.build_default_implementations(),
        services,
    )

    result = engine.execute(wrong_way_skill(), str(video_path))

    frames = result.values["frames"]
    assert [frame.frame_index for frame in frames.items] == [0, 1, 2, 3]
    assert [frame.timestamp for frame in frames.items] == pytest.approx(
        [0.0, 0.5, 1.0, 1.5]
    )
    tracks = result.values["tracks"]
    assert len(tracks.items) == 3
    assert sorted(len(track.history) for track in tracks.items) == [4, 4, 4]
    events = result.outputs["events"]
    assert len(events.items) == 1
    assert events.items[0].label == "逆行车辆"
    assert events.items[0].start_time == pytest.approx(1.5)
    assert events.items[0].end_time == pytest.approx(1.5)
    assert [entry.node_id for entry in result.trace] == [
        "video",
        "frames",
        "vehicles",
        "tracks",
        "headings",
        "majority",
        "opposite",
        "confirmed",
        "alerts",
    ]
