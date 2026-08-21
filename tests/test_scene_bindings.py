from __future__ import annotations

import json
from pathlib import Path

import pytest

from app_v2 import V2AppController
from core.registry import build_default_registry


ROOT = Path(__file__).resolve().parents[1]


def _controller(tmp_path):
    return V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=None,
        rex=None,
    )


def _preset(prefix: str) -> str:
    return next((ROOT / "presets_v2").glob(f"{prefix}*.json")).read_text("utf-8")


def test_manual_roi_binding_supports_rectangle_and_polygon(tmp_path):
    controller = _controller(tmp_path)
    source = _preset("P07")

    polygon = controller.apply_manual_roi_points(
        source,
        "仅视频",
        "no_parking_region",
        "polygon",
        "[[0.1,0.2],[0.9,0.2],[0.8,0.9],[0.2,0.9]]",
    )
    node = next(
        item for item in json.loads(polygon)["variants"]["video"]["nodes"]
        if item["id"] == "no_parking_region"
    )
    assert node["params"] == {
        "shape": "polygon",
        "points": [[0.1, 0.2], [0.9, 0.2], [0.8, 0.9], [0.2, 0.9]],
    }

    rectangle = controller.apply_manual_roi_points(
        source,
        "仅视频",
        "no_parking_region",
        "rectangle",
        "[[0.2,0.3],[0.8,0.9]]",
    )
    node = next(
        item for item in json.loads(rectangle)["variants"]["video"]["nodes"]
        if item["id"] == "no_parking_region"
    )
    assert node["params"]["shape"] == "rectangle"


def test_manual_lane_direction_switches_auto_lane_reference_to_explicit_vector(tmp_path):
    controller = _controller(tmp_path)
    source = _preset("P05")

    updated = controller.apply_manual_direction(
        source,
        "仅视频",
        "lane_references",
        0.2,
        0.8,
        0.8,
        0.2,
    )
    node = next(
        item for item in json.loads(updated)["variants"]["video"]["nodes"]
        if item["id"] == "lane_references"
    )
    assert node["op"] == "direction.manual@1.0"
    assert node["inputs"] == {}
    assert node["params"]["vector"] == pytest.approx([0.6, -0.6])
