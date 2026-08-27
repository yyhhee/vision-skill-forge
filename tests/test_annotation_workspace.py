from __future__ import annotations

import json

import cv2
import numpy as np
from PIL import Image

from core.annotation import (
    annotations_from_package,
    extract_annotation_frame,
    normalize_canvas_point,
    render_annotation_workspace,
)
from core.registry import build_default_registry
from core.schema import SkillPackage


def test_annotation_frame_uses_original_image_and_selected_video_timestamp(tmp_path):
    image_path = tmp_path / "original.png"
    Image.new("RGB", (83, 47), (10, 20, 30)).save(image_path)
    image_frame = extract_annotation_frame(image_path, 99.0)
    assert image_frame.media_type == "image"
    assert image_frame.image.size == (83, 47)
    assert image_frame.timestamp == 0.0
    assert image_frame.frame_index == 0

    video_path = tmp_path / "source.avi"
    writer = cv2.VideoWriter(
        str(video_path), cv2.VideoWriter_fourcc(*"MJPG"), 2.0, (80, 40)
    )
    for value in (0, 80, 160, 240):
        writer.write(np.full((40, 80, 3), value, dtype=np.uint8))
    writer.release()

    video_frame = extract_annotation_frame(video_path, 1.0)
    assert video_frame.media_type == "video"
    assert video_frame.image.size == (80, 40)
    assert video_frame.frame_index == 2
    assert video_frame.timestamp == 1.0


def test_clear_saved_annotations_only_removes_existing_geometry(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    source = tmp_path / "annotation.png"
    Image.new("RGB", (120, 80), "white").save(source)
    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    package = _lane_package()
    state = {"tool": "polygon", "points": [[0.2, 0.2], [0.3, 0.3]]}

    updated_json, _, updated_state, points_json, status = (
        controller.clear_saved_annotations(
            controller._dump(package),
            "video",
            str(source),
            0.0,
            state,
        )
    )

    updated = SkillPackage.model_validate_json(updated_json)
    assert annotations_from_package(updated, "video") == {
        "regions": [],
        "directions": [],
    }
    assert updated.semantic_ir.model_dump(mode="json") == package.semantic_ir.model_dump(mode="json")
    assert updated_state["points"] == []
    assert json.loads(points_json) == []
    assert "全部已保存标注" in status


def test_canvas_clicks_are_normalized_and_clamped_to_original_media():
    assert normalize_canvas_point(100, 25, 200, 100) == [0.5, 0.25]
    assert normalize_canvas_point(-5, 120, 200, 100) == [0.0, 1.0]


def test_workspace_renders_existing_roi_direction_and_draft_geometry():
    base = Image.new("RGB", (200, 100), "white")
    annotations = {
        "regions": [
            {
                "id": "lane_a",
                "label": "Lane A",
                "shape": "rectangle",
                "points": [[0.05, 0.05], [0.45, 0.45]],
            }
        ],
        "directions": [
            {
                "key": "lane_a",
                "start": [0.1, 0.8],
                "end": [0.9, 0.8],
            }
        ],
    }
    rendered = render_annotation_workspace(
        base,
        annotations,
        draft_tool="polygon",
        draft_points=[[0.55, 0.1], [0.8, 0.2], [0.7, 0.5]],
    )

    assert rendered.getpixel((50, 5)) != (255, 255, 255)
    assert rendered.getpixel((100, 80)) != (255, 255, 255)
    assert rendered.getpixel((110, 10)) != (255, 255, 255)


def _pending_package() -> SkillPackage:
    from tests.test_configuration_slots import _pending_package as factory

    return factory()


def test_controller_binds_canvas_points_to_declared_slot_not_internal_node_id(tmp_path):
    from app_v2 import V2AppController

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    package = _pending_package()
    updated, slots, status = controller.bind_annotation(
        controller._dump(package),
        "video",
        "no_parking_region",
        "polygon",
        json.dumps([[0.1, 0.2], [0.9, 0.2], [0.8, 0.9], [0.2, 0.9]]),
        "",
        "",
    )

    node = next(
        item
        for item in json.loads(updated)["variants"]["video"]["nodes"]
        if item["id"] == "no_parking_region"
    )
    assert node["params"]["shape"] == "polygon"
    assert slots[0]["configured"] is True
    assert "已绑定" in status


def test_controller_uses_the_only_annotation_slot_when_ui_value_is_temporarily_empty(tmp_path):
    from app_v2 import V2AppController

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    updated, _, status = controller.bind_annotation(
        controller._dump(_pending_package()),
        "video",
        None,
        "rectangle",
        json.dumps([[0.1, 0.2], [0.9, 0.8]]),
    )

    node = next(
        item
        for item in json.loads(updated)["variants"]["video"]["nodes"]
        if item["id"] == "no_parking_region"
    )
    assert node["params"]["points"] == [[0.1, 0.2], [0.9, 0.8]]
    assert "no_parking_region" in status


def test_controller_ingests_media_and_builds_original_frame_preview(tmp_path):
    from app_v2 import V2AppController

    source = tmp_path / "camera.png"
    Image.new("RGB", (101, 57), "navy").save(source)
    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    stored_path, metadata, preview, state, status = controller.ingest_media(
        str(source), 0.0
    )

    assert stored_path != str(source)
    assert metadata["width"] == 101
    assert metadata["height"] == 57
    assert preview.size == (101, 57)
    assert state["points"] == []
    assert state["asset_path"] == stored_path
    assert "原始媒体已保存" in status


def test_controller_canvas_click_undo_clear_and_slot_choices_are_generic(tmp_path):
    from app_v2 import V2AppController

    source = tmp_path / "frame.png"
    Image.new("RGB", (200, 100), "white").save(source)
    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    stored_path, _, _, state, _ = controller.ingest_media(str(source), 0.0)
    package_json = controller._dump(_pending_package())

    choices, rows = controller.annotation_slots(package_json, "video")
    assert choices[0][1] == "no_parking_region"
    assert rows[0]["configured"] is False

    _, state, points_json, _ = controller.add_annotation_point(
        package_json,
        "video",
        stored_path,
        0.0,
        "rectangle",
        state,
        20,
        25,
    )
    _, state, points_json, _ = controller.add_annotation_point(
        package_json,
        "video",
        stored_path,
        0.0,
        "rectangle",
        state,
        180,
        75,
    )
    assert json.loads(points_json) == [[0.1, 0.25], [0.9, 0.75]]

    _, state, points_json, _ = controller.undo_annotation_point(
        package_json, "video", stored_path, 0.0, state
    )
    # rectangle/direction drag shapes are atomic: undo clears the whole draft.
    assert json.loads(points_json) == []

    # polygon undo pops a single vertex.
    for point in ((20, 25), (60, 25), (40, 80)):
        _, state, _, _ = controller.add_annotation_point(
            package_json, "video", stored_path, 0.0, "polygon", state, *point
        )
    _, state, points_json, _ = controller.undo_annotation_point(
        package_json, "video", stored_path, 0.0, state
    )
    assert len(json.loads(points_json)) == 2

    _, state, points_json, _ = controller.clear_annotation_points(
        package_json, "video", stored_path, 0.0, state
    )
    assert json.loads(points_json) == []


def test_controller_drag_annotation_uses_two_normalized_endpoints(tmp_path):
    from app_v2 import V2AppController

    source = tmp_path / "frame.png"
    Image.new("RGB", (200, 100), "white").save(source)
    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    stored_path, _, _, state, _ = controller.ingest_media(str(source), 0.0)
    package_json = controller._dump(_pending_package())

    _, _, points_json, _ = controller.set_annotation_drag(
        package_json,
        "video",
        stored_path,
        0.0,
        "rectangle",
        state,
        json.dumps({"start": [20, 25], "end": [180, 75]}),
    )

    assert json.loads(points_json) == [[0.1, 0.25], [0.9, 0.75]]


def test_controller_drag_annotation_scales_displayed_canvas_coordinates(tmp_path):
    from app_v2 import V2AppController

    source = tmp_path / "frame.png"
    Image.new("RGB", (200, 100), "white").save(source)
    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    stored_path, _, _, state, _ = controller.ingest_media(str(source), 0.0)
    package_json = controller._dump(_pending_package())

    _, _, points_json, _ = controller.set_annotation_drag(
        package_json,
        "video",
        stored_path,
        0.0,
        "direction",
        state,
        json.dumps({
            "start": [20, 25],
            "end": [90, 45],
            "canvas_size": [100, 50],
        }),
    )

    assert json.loads(points_json) == [[0.2, 0.5], [0.9, 0.9]]


def test_annotation_wizard_is_generic_for_single_and_named_slots(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package, _pending_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    single = controller.annotation_wizard_state(
        controller._dump(_pending_package()), "video"
    )
    assert single["complete"] is False
    assert single["current_slot"] == "no_parking_region"
    assert single["slots"][0]["kind"] == "region"
    assert single["slots"][0]["pending_items"] == ["no_parking_region"]

    lane_data = _lane_package().model_dump(mode="json")
    lane_variant = lane_data["variants"]["video"]
    regions = next(
        node for node in lane_variant["nodes"] if node["id"] == "lane_regions"
    )
    regions["params"] = {"regions": [
        {
            "id": "lane_a", "label": "A", "shape": "polygon",
            "points": [[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [0.0, 1.0]],
        },
        {
            "id": "lane_b", "label": "B", "shape": "polygon",
            "points": [[0.5, 0.0], [1.0, 0.0], [1.0, 1.0], [0.5, 1.0]],
        },
    ]}
    directions = next(
        node for node in lane_variant["nodes"] if node["id"] == "lane_references"
    )
    directions["params"] = {"directions": [{
        "key": "lane_a", "vector": [0.0, -1.0],
        "start": [0.25, 0.8], "end": [0.25, 0.2],
    }]}
    lane_package = SkillPackage.model_validate(lane_data)

    wizard = controller.annotation_wizard_state(
        controller._dump(lane_package), "video"
    )
    by_id = {item["slot_id"]: item for item in wizard["slots"]}
    assert by_id["lane_regions"]["configured_items"] == ["lane_a", "lane_b"]
    assert by_id["lane_regions"]["pending_items"] == ["new_item"]
    assert by_id["lane_directions"]["depends_on"] == "lane_regions"
    assert by_id["lane_directions"]["pending_items"] == ["lane_b"]
    # Save-and-continue advances to the missing direction. The explicit add
    # button remains the way to create another unbounded named region.
    assert wizard["current_slot"] == "lane_directions"
    assert wizard["current_item"] == "lane_b"
    markdown = controller.annotation_wizard_markdown(
        controller._dump(lane_package), "video"
    )
    assert "lane_regions" in markdown
    assert "lane_directions" in markdown
    assert "lane_b" in markdown
    assert "依赖" in markdown
    tool, item_id, item_label = controller.annotation_wizard_defaults(
        controller._dump(lane_package), "video", "lane_directions"
    )
    assert tool == "direction"
    assert item_id == "lane_b"
    assert item_label == "lane_b"


def test_annotation_wizard_prioritizes_unconfigured_region_set_and_hides_duplicates(
    tmp_path,
):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    data = _lane_package().model_dump(mode="json")
    variant = data["variants"]["video"]
    variant["configuration_slots"] = [
        slot
        for slot in variant["configuration_slots"]
        if slot["slot_id"] != "lane_directions"
    ]
    variant["nodes"] = [
        node for node in variant["nodes"] if node["id"] != "lane_references"
    ]
    region_node = next(node for node in variant["nodes"] if node["id"] == "lane_regions")
    region_node["params"]["regions"] = [
        {
            "id": "region_1",
            "label": "区域1",
            "shape": "rectangle",
            "points": [[0.1, 0.1], [0.4, 0.8]],
        }
    ]
    second_node = {
        **region_node,
        "id": "region_2_regions",
        "params": {"regions": []},
    }
    variant["nodes"].append(second_node)
    first_slot = next(
        slot for slot in variant["configuration_slots"] if slot["slot_id"] == "lane_regions"
    )
    second_slot = {
        **first_slot,
        "slot_id": "region_2",
        "label": "区域2",
        "binding": {"node_id": "region_2_regions", "parameter": "regions"},
    }
    variant["configuration_slots"].extend([second_slot, dict(second_slot)])
    package = SkillPackage.model_validate(data)

    wizard = controller.annotation_wizard_state(controller._dump(package), "video")

    assert wizard["current_slot"] == "region_2"
    assert [row["slot_id"] for row in wizard["slots"]].count("region_2") == 1


def test_first_automatic_named_region_uses_the_business_slot_label(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    package = _lane_package()
    region_node = next(
        node for node in package.variants["video"].nodes if node.id == "lane_regions"
    )
    region_node.params = {"regions": []}
    expected_label = next(
        slot.label
        for slot in package.variants["video"].configuration_slots
        if slot.slot_id == "lane_regions"
    )
    _, _, default_label = controller.annotation_wizard_defaults(
        controller._dump(package), "video", "lane_regions"
    )
    assert default_label == expected_label
    updated, _, _ = controller.bind_annotation(
        controller._dump(package),
        "video",
        "lane_regions",
        "rectangle",
        json.dumps([[0.1, 0.1], [0.4, 0.8]]),
        "",
        "",
    )

    region_node = next(
        node
        for node in json.loads(updated)["variants"]["video"]["nodes"]
        if node["id"] == "lane_regions"
    )
    assert region_node["params"]["regions"][0]["label"] == expected_label


def test_editor_document_syncs_saved_annotation_geometry(tmp_path):
    from app_v2 import V2AppController
    from core.legacy_importer import import_skill_package
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    pending = _lane_package()
    document = import_skill_package(pending)
    data = pending.model_dump(mode="json")
    region_node = next(
        node for node in data["variants"]["video"]["nodes"] if node["id"] == "lane_regions"
    )
    region_node["params"]["regions"] = [
        {
            "id": "lane_1",
            "label": "车道1",
            "shape": "rectangle",
            "points": [[0.1, 0.2], [0.4, 0.9]],
        }
    ]
    annotated = SkillPackage.model_validate(data)

    synced = controller._editor_document(
        controller._dump(annotated), controller._dump(document)
    )

    collection = next(
        item
        for item in synced.scene_profiles[0].collections
        if item.requirement_id == "video_lane_regions"
    )
    assert collection.completed is True
    assert collection.items[0].geometry == {
        "shape": "rectangle",
        "points": [[0.1, 0.2], [0.4, 0.9]],
    }


def test_annotation_wizard_defaults_to_its_next_dependency_aware_step(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _pending_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    tool, item_id, label = controller.annotation_wizard_defaults(
        controller._dump(_pending_package()), "video", None
    )

    assert tool in {"rectangle", "polygon"}
    assert item_id == "no_parking_region"
    assert label == "no_parking_region"


def test_annotation_wizard_prefers_regions_over_direction_awaiting_source(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    data = _lane_package().model_dump(mode="json")
    for node in data["variants"]["video"]["nodes"]:
        if node["id"] == "lane_regions":
            node["params"] = {"regions": []}
        elif node["id"] == "lane_references":
            node["params"] = {"directions": []}
    package = SkillPackage.model_validate(data)

    wizard = controller.annotation_wizard_state(controller._dump(package), "video")

    assert wizard["current_slot"] == "lane_regions"
    assert wizard["current_item"] == "new_item"


def test_named_region_wizard_assigns_a_reusable_next_region_id(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    tool, item_id, label = controller.annotation_wizard_defaults(
        controller._dump(_lane_package()), "video", "lane_regions"
    )

    assert tool in {"rectangle", "polygon"}
    assert item_id == "lane_regions_3"
    assert label == "lane_regions_3"


def test_direction_wizard_does_not_expose_awaiting_source_as_item_id(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    data = _lane_package().model_dump(mode="json")
    for node in data["variants"]["video"]["nodes"]:
        if node["id"] == "lane_regions":
            node["params"] = {"regions": []}
        elif node["id"] == "lane_references":
            node["params"] = {"directions": []}
    package = SkillPackage.model_validate(data)

    tool, item_id, label = controller.annotation_wizard_defaults(
        controller._dump(package), "video", "lane_directions"
    )

    assert tool == "direction"
    assert item_id == ""
    assert label == ""


def test_annotation_wizard_continues_from_saved_lane_to_its_missing_direction(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    data = _lane_package().model_dump(mode="json")
    for node in data["variants"]["video"]["nodes"]:
        if node["id"] == "lane_references":
            node["params"] = {"directions": []}
    package = SkillPackage.model_validate(data)

    wizard = controller.annotation_wizard_state(controller._dump(package), "video")

    assert wizard["current_slot"] == "lane_directions"
    assert wizard["current_item"] == "lane_left"


def test_annotation_selection_clears_stale_draft_before_starting_another_region(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    tool, item_id, item_label, draft = controller.annotation_selection_defaults(
        controller._dump(_lane_package()),
        "video",
        "lane_regions",
        {"tool": "direction", "points": [[0.2, 0.2], [0.8, 0.8]]},
    )

    assert tool == "polygon"
    assert item_id == "lane_regions_3"
    assert item_label == "lane_regions_3"
    assert draft == {"tool": "polygon", "points": []}


def test_controller_routes_stale_region_slot_arrow_to_missing_direction(tmp_path):
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    data = _lane_package().model_dump(mode="json")
    for node in data["variants"]["video"]["nodes"]:
        if node["id"] == "lane_references":
            node["params"] = {"directions": []}
    package = SkillPackage.model_validate(data)

    updated, _, status = controller.bind_annotation(
        controller._dump(package),
        "video",
        "lane_regions",
        "direction",
        json.dumps([[0.1, 0.8], [0.4, 0.2]]),
        "lane_left",
        "lane_left",
    )

    directions = next(
        node for node in json.loads(updated)["variants"]["video"]["nodes"]
        if node["id"] == "lane_references"
    )["params"]["directions"]
    assert [item["key"] for item in directions] == ["lane_left"]
    assert "lane_directions" in status


def test_region_slot_keeps_direction_arrow_as_a_drawing_tool(tmp_path):
    """Removing this option makes the per-lane direction workflow unreachable."""
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    choices = controller.annotation_tool_choices(
        controller._dump(_lane_package()), "video", "lane_regions"
    )

    assert choices == [
        ("矩形", "rectangle"),
        ("多边形", "polygon"),
        ("方向箭头", "direction"),
    ]


def test_annotation_slot_rows_mark_only_the_selected_slot(tmp_path):
    """The visible slot-state panel must follow the slot dropdown selection."""
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )

    rows = controller.annotation_slots_with_selection(
        controller._dump(_lane_package()), "video", "lane_directions"
    )

    assert {row["slot_id"]: row["selected"] for row in rows} == {
        "lane_regions": False,
        "lane_directions": True,
    }


def test_selecting_direction_from_region_targets_first_missing_lane_direction(tmp_path):
    """The arrow must switch both the slot and bound lane before drawing."""
    from app_v2 import V2AppController
    from tests.test_configuration_slots import _lane_package

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        asset_root=tmp_path / "assets",
        planner=None,
        rex=None,
    )
    data = _lane_package().model_dump(mode="json")
    for node in data["variants"]["video"]["nodes"]:
        if node["id"] == "lane_references":
            node["params"] = {"directions": []}
    package = SkillPackage.model_validate(data)

    slot_id, tool, item_id, item_label, draft = (
        controller.annotation_tool_selection_defaults(
            controller._dump(package), "video", "lane_regions", "direction"
        )
    )

    assert slot_id == "lane_directions"
    assert tool == "direction"
    assert item_id == "lane_left"
    assert item_label == "lane_left"
    assert draft == {"tool": "direction", "points": []}
