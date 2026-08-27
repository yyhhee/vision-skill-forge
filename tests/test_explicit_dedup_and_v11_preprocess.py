from __future__ import annotations

import pytest
from PIL import Image

from core.context import ObjectSet, VisualObject
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler


def _object(
    object_id,
    label,
    bbox,
    *,
    frame_index=0,
    source_entity_id=None,
    localization_score=1.0,
):
    return VisualObject(
        id=object_id,
        label=label,
        phrase=label,
        bbox=bbox,
        frame_index=frame_index,
        timestamp=0.0,
        source_node="ground",
        source_entity_id=source_entity_id,
        original_size=(100, 100),
        localization_score=localization_score,
    )


def _direct_ir():
    return CanonicalSemanticIR.model_validate(
        {
            "schema_version": "1.0",
            "mode": "direct_grounding",
            "target": {
                "concept": "vehicle",
                "source_span": "车辆",
                "phrases": ["vehicle", "car"],
            },
            "constraints": [],
            "logic": "all",
            "unresolved": [],
            "semantic_hash": "b" * 64,
        }
    )


def test_dedup_is_same_label_same_frame_only_and_keeps_first_source_order():
    from operators.perception import objects_deduplicate

    objects = ObjectSet(
        [
            _object("full", "car", (0.1, 0.1, 0.5, 0.5)),
            _object("tile", "car", (0.2, 0.2, 0.4, 0.4)),
            _object("other_label", "truck", (0.2, 0.2, 0.4, 0.4)),
            _object("other_frame", "car", (0.2, 0.2, 0.4, 0.4), frame_index=1),
        ]
    )

    result = objects_deduplicate(
        {"objects": objects},
        {"metric": "ios", "threshold": 0.5, "keep": "first"},
        None,
        "dedup",
    )

    assert [item.id for item in result.items] == [
        "full",
        "other_label",
        "other_frame",
    ]


def test_iou_and_ios_are_distinct_explicit_metrics():
    from operators.perception import objects_deduplicate

    objects = ObjectSet(
        [
            _object("large", "car", (0.0, 0.0, 1.0, 1.0)),
            _object("small", "car", (0.1, 0.1, 0.4, 0.4)),
        ]
    )
    ios = objects_deduplicate(
        {"objects": objects},
        {"metric": "ios", "threshold": 0.5, "keep": "first"},
        None,
        "ios",
    )
    iou = objects_deduplicate(
        {"objects": objects},
        {"metric": "iou", "threshold": 0.5, "keep": "first"},
        None,
        "iou",
    )

    assert [item.id for item in ios.items] == ["large"]
    assert [item.id for item in iou.items] == ["large", "small"]


def test_best_localization_dedup_prefers_precise_tile_box_over_coarse_full_frame():
    from operators.perception import objects_deduplicate

    objects = ObjectSet([
        _object(
            "coarse_full_frame", "car", (0.1, 0.1, 0.5, 0.5),
            localization_score=1.0,
        ),
        _object(
            "precise_tile", "car", (0.2, 0.2, 0.4, 0.4),
            localization_score=2.5,
        ),
    ])

    result = objects_deduplicate(
        {"objects": objects},
        {"metric": "ios", "threshold": 0.7, "keep": "best_localization"},
        None,
        "dedup",
    )

    assert [item.id for item in result.items] == ["precise_tile"]


def test_localization_score_penalizes_boxes_cut_by_an_internal_tile_edge():
    from core.context import Frame
    from operators.perception import _localization_score

    full = Frame(Image.new("RGB", (100, 100)), (100, 100))
    tile = Frame(
        Image.new("RGB", (50, 50)),
        (100, 100),
        source_rect=(0.25, 0.25, 0.75, 0.75),
    )

    full_score = _localization_score(full, (0.2, 0.2, 0.4, 0.4))
    precise_tile_score = _localization_score(tile, (0.2, 0.2, 0.4, 0.4))
    clipped_tile_score = _localization_score(tile, (0.0, 0.2, 0.4, 0.4))

    assert precise_tile_score > full_score > clipped_tile_score


def test_local_evidence_from_different_subjects_is_not_cross_subject_deduplicated():
    from operators.perception import objects_deduplicate

    objects = ObjectSet([
        _object(
            "person_a_helmet",
            "helmet",
            (0.1, 0.1, 0.3, 0.3),
            source_entity_id="person_a",
        ),
        _object(
            "person_b_helmet",
            "helmet",
            (0.1, 0.1, 0.3, 0.3),
            source_entity_id="person_b",
        ),
    ])

    result = objects_deduplicate(
        {"objects": objects},
        {"metric": "ios", "threshold": 0.5, "keep": "first"},
        None,
        "dedup",
    )

    assert [item.id for item in result.items] == [
        "person_a_helmet",
        "person_b_helmet",
    ]


def test_v2_compiler_emits_raw_rex_then_explicit_dedup_and_visible_resize():
    package = WorkflowCompiler(build_default_registry()).compile(
        _direct_ir(),
        original_instruction="检测车辆",
        requested_accept=["image", "video"],
        skill_id="vehicle_demo",
        display_name="车辆",
    )

    for media_type in ("image", "video"):
        nodes = package.variants[media_type].nodes
        ops = [node.op for node in nodes]
        assert "image.resize@1.1" in ops
        assert "rex.ground@1.1" in ops
        assert "objects.deduplicate@1.0" in ops
        raw = next(node for node in nodes if node.id == "candidates_raw")
        dedup = next(node for node in nodes if node.id == "candidates")
        resize = next(node for node in nodes if node.id == "resized")
        assert resize.params["mode"] == "identity"
        assert raw.inputs["frames"] == "$resized"
        assert "deduplicate_metric" not in raw.params
        assert dedup.inputs == {"objects": "$candidates_raw"}
        assert dedup.params == {
            "metric": "ios",
            "threshold": 0.5,
            "keep": "first",
        }

    sample = next(
        node for node in package.variants["video"].nodes
        if node.op == "video.sample@1.1"
    )
    assert sample.params == {
        "mode": "fps",
        "fps": 1.0,
        "start_seconds": 0.0,
        "end_seconds": None,
        "max_frames": None,
    }


def test_presets_keep_their_explicit_validated_resize_policy():
    from core.preset_definitions import build_preset_definitions
    from core.preset_factory import build_package

    definition = next(
        item for item in build_preset_definitions()
        if item.skill_id == "road_debris"
    )
    package = build_package(definition)

    for media_type in ("image", "video"):
        resize = next(
            node for node in package.variants[media_type].nodes
            if node.op == "image.resize@1.1" and node.id == "resized"
        )
        assert resize.params == {"mode": "long_side", "long_side": 1280}


def test_tile_v11_supports_independent_x_y_overlap_and_transform_chain():
    from core.context import Frame, FrameSet
    from operators.preprocess import image_tile

    frames = FrameSet([Frame(Image.new("RGB", (100, 80)), (100, 80))])
    result = image_tile(
        {"frames": frames},
        {
            "tile_width": 60,
            "tile_height": 50,
            "overlap_x": 0.5,
            "overlap_y": 0.0,
            "include_full_frame": True,
        },
        None,
        "tiles",
    )

    assert len(result.items) == 1 + 3 * 2
    assert result.items[0].transform.steps == ()
    assert result.items[1].transform.steps[-1].parameters["crop_box"] == [0, 0, 60, 50]
    assert result.items[-1].transform.steps[-1].parameters["crop_box"] == [40, 30, 100, 80]
