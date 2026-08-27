from __future__ import annotations

from pathlib import Path

import pytest

from core.registry import build_default_registry
from core.schema import SkillPackage
from core.validator import validate_skill_package


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_MEDIA = {
    "P01": ["image", "video"],
    "P02": ["image", "video"],
    "P03": ["image", "video"],
    "P04": ["video"],
    "P05": ["video"],
    "P06": ["video"],
    "P07": ["video"],
    "P08": ["image", "video"],
    "P09": ["image", "video"],
    "P10": ["image", "video"],
    "P11": ["image", "video"],
    "P12": ["video"],
    "P13": ["image", "video"],
}

REQUIRED_OPS = {
    "P01": {
        "rex.ground@1.1", "objects.deduplicate@1.0",
        "visual.color_fraction@1.0", "logic.any@1.0", "filter.apply@1.0",
    },
    "P02": {"rex.ground@1.1", "objects.deduplicate@1.0"},
    "P03": {"rex.ground@1.1", "objects.deduplicate@1.0"},
    "P04": {
        "region.manual_set@1.0", "measure.region_count@1.0",
        "logic.compare@1.0", "temporal.persist@1.0",
    },
    "P05": {
        "track.iou@1.0", "measure.heading@1.0", "region.manual_set@1.0",
        "direction.manual_set@1.0", "logic.heading_by_lane@1.0",
        "temporal.persist@1.0",
    },
    "P06": {
        "track.iou@1.0", "region.manual@1.0", "spatial.inside@1.0",
        "temporal.persist@1.0",
    },
    "P07": {
        "track.iou@1.0", "region.manual@1.0", "spatial.inside@1.0",
        "temporal.persist@1.0",
    },
    "P08": {
        "region.from_objects@1.0", "spatial.inside@1.0",
        "filter.apply@1.0",
    },
    "P09": {
        "spatial.associate@1.0", "logic.not@1.0", "filter.apply@1.0",
    },
    "P10": {
        "spatial.associate@1.0", "logic.not@1.0", "filter.apply@1.0",
    },
    "P11": {"rex.ground@1.1", "objects.deduplicate@1.0"},
    "P12": {"track.iou@1.0", "temporal.persist@1.0"},
    "P13": {
        "image.tile@1.1", "rex.ground@1.1", "objects.deduplicate@1.0",
    },
}


def _load_all():
    files = sorted((ROOT / "presets_v2").glob("P*.json"))
    return [(path, SkillPackage.model_validate_json(path.read_text("utf-8"))) for path in files]


def test_all_13_v2_presets_exist_validate_and_match_media_contracts():
    loaded = _load_all()
    assert len(loaded) == 13
    registry = build_default_registry()
    for path, package in loaded:
        preset_id = path.stem[:3]
        assert list(package.input.requested_accept) == EXPECTED_MEDIA[preset_id]
        assert list(package.input.accept) == EXPECTED_MEDIA[preset_id]
        assert set(package.variants) == set(EXPECTED_MEDIA[preset_id])
        assert package.input.video_guidance.recommended_max_duration_seconds == 30
        assert package.input.video_guidance.enforcement == "warn_only"
        assert validate_skill_package(package, registry) == []
        for media_type in EXPECTED_MEDIA[preset_id]:
            variant = package.select_variant(media_type)
            ops = {node.op for node in variant.nodes}
            assert REQUIRED_OPS[preset_id] <= ops
            if media_type == "video":
                assert "video.sample@1.1" in ops
            else:
                assert "video.sample@1.1" not in ops


def test_person_fall_preset_uses_one_precise_active_or_lying_pose_grounding():
    package = SkillPackage.model_validate_json(
        (ROOT / "presets_v2" / "P12_person_fall.json").read_text("utf-8")
    )
    pose = package.semantic_ir.constraints[0]
    fallen_grounding = next(
        node
        for node in package.variants["video"].nodes
        if node.id == "fallen_people_raw"
    )

    assert pose.kind == "pose"
    assert pose.value == "fallen_or_lying"
    assert pose.phrases == ["person lying on the ground"]
    phrases = fallen_grounding.params["targets"][0]["phrases"]
    assert phrases == [
        "person actively falling toward the ground",
        "person losing balance and collapsing",
        "person bent low while falling",
        "person lying on the ground",
    ]
    assert not {"person fallen", "fallen person", "person who has fallen"} & set(phrases)
    assert sum(
        node.op == "rex.ground@1.1"
        for node in package.variants["video"].nodes
    ) == 1


def test_person_fall_preset_tracks_direct_pose_evidence_before_persistence():
    package = SkillPackage.model_validate_json(
        (ROOT / "presets_v2" / "P12_person_fall.json").read_text("utf-8")
    )
    nodes = {node.id: node for node in package.variants["video"].nodes}

    events = nodes["events"]
    assert nodes["tracks"].inputs == {"objects": "$fallen_people"}
    assert nodes["fallen_present"].op == "reduce.exists@1.0"
    assert nodes["fallen_present"].inputs == {"sets": "$tracks"}
    assert nodes["fallen_present"].params == {"scope": "entity"}
    assert events.inputs == {"condition": "$fallen_present"}
    assert nodes["draw"].params["event_time_window"] == "track_history"


def test_every_v2_rex_node_has_explicit_same_label_dedup_consumer():
    forbidden = {"not", "without", "exclude", "except"}
    for _, package in _load_all():
        for variant in package.variants.values():
            node_by_id = {node.id: node for node in variant.nodes}
            for node in variant.nodes:
                if node.op != "rex.ground@1.1":
                    continue
                phrases = [
                    phrase.lower()
                    for target in node.params["targets"]
                    for phrase in target["phrases"]
                ]
                assert not any(
                    token in phrase.split() for phrase in phrases for token in forbidden
                )
                consumers = [
                    candidate for candidate in variant.nodes
                    if candidate.op == "objects.deduplicate@1.0"
                    and candidate.inputs.get("objects") == f"${node.id}"
                ]
                assert len(consumers) == 1
                assert consumers[0].params["keep"] in {
                    "first", "best_localization"
                }
                assert consumers[0].params["metric"] in {"ios", "iou"}


def test_highway_congestion_prefers_precise_tile_boxes_without_tracking():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P04*.json")).read_text("utf-8")
    )
    nodes = {node.id: node for node in package.variants["video"].nodes}

    assert nodes["vehicles"].params["keep"] == "best_localization"
    assert nodes["vehicle_box_shape"].params == {
        "dimension": "aspect_ratio",
        "value": "horizontal",
        "aspect_ratio_threshold": 0.6,
    }
    assert nodes["vehicles_localized"].inputs == {
        "objects": "$vehicles",
        "condition": "$vehicle_box_shape",
    }
    assert nodes["vehicles_in_lanes"].op == "objects.filter_by_regions@1.0"
    assert nodes["vehicles_in_lanes"].inputs == {
        "objects": "$vehicles_localized",
        "regions": "$lane_regions",
    }
    assert nodes["lane_count"].inputs["objects"] == "$vehicles_in_lanes"
    assert nodes["draw"].inputs["objects"] == "$vehicles_in_lanes"
    assert "tracks" not in nodes
    assert "lane_speed" not in nodes
    assert "slow" not in nodes
    assert nodes["draw"].params["show_labels"] is False
    assert nodes["draw"].params["show_track_id"] is False


def test_special_vehicle_v2_preset_keeps_12_independent_canonical_labels():
    path = next((ROOT / "presets_v2").glob("P03*.json"))
    package = SkillPackage.model_validate_json(path.read_text("utf-8"))
    expected = [
        "消防车", "救护车", "警车", "工程抢险车", "道路清障车", "环卫车",
        "油罐车", "混凝土搅拌车", "混凝土泵车", "汽车吊", "高空作业车",
        "危险品运输车",
    ]
    for variant in package.variants.values():
        ground = next(node for node in variant.nodes if node.id == "special_vehicles_raw")
        assert [target["label"] for target in ground.params["targets"]] == expected
        assert all(target["phrases"] for target in ground.params["targets"])
        dedup = next(node for node in variant.nodes if node.id == "special_vehicles")
        assert dedup.params == {"metric": "ios", "threshold": 0.5, "keep": "first"}


def test_fire_smoke_preset_validates_grounding_with_explicit_visual_evidence():
    path = next((ROOT / "presets_v2").glob("P01*.json"))
    package = SkillPackage.model_validate_json(path.read_text("utf-8"))

    for variant in package.variants.values():
        evidence = [
            node for node in variant.nodes
            if node.op == "visual.color_fraction@1.0"
        ]
        assert {node.params["color"] for node in evidence} == {
            "black", "gray", "red", "orange", "yellow"
        }
        assert all(node.params["selection_mode"] == "dominant" for node in evidence)
        combined = next(node for node in variant.nodes if node.id == "fire_smoke_evidence")
        assert combined.op == "logic.any@1.0"
        filtered = next(node for node in variant.nodes if node.id == "fire_smoke_validated")
        assert filtered.op == "filter.apply@1.0"
        assert filtered.inputs == {
            "objects": "$fire_smoke",
            "condition": "$fire_smoke_evidence",
        }
        assert variant.outputs["objects"] == "$fire_smoke_validated"


def test_congestion_and_wrong_way_use_explicit_temporal_conditions():
    congestion = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P04*.json")).read_text("utf-8")
    ).select_variant("video")
    lanes = next(node for node in congestion.nodes if node.id == "lane_regions")
    count = next(node for node in congestion.nodes if node.id == "lane_count")
    tile = next(node for node in congestion.nodes if node.op == "image.tile@1.1")
    ground = next(node for node in congestion.nodes if node.id == "vehicles_raw")
    dedup = next(node for node in congestion.nodes if node.id == "vehicles")
    assert lanes.op == "region.manual_set@1.0"
    assert lanes.params == {"regions": []}
    assert count.op == "measure.region_count@1.0"
    assert not any(node.op == "track.iou@1.0" for node in congestion.nodes)
    assert not any(node.op == "measure.region_speed@1.0" for node in congestion.nodes)
    assert tile.params["include_full_frame"] is True
    assert ground.inputs["frames"] == "$tiles"
    assert {"car", "SUV", "van", "bus"}.issubset(
        set(ground.params["targets"][0]["phrases"])
    )
    assert dedup.params["threshold"] == 0.7
    assert congestion.outputs["measurements_1"] == "$lane_count"
    assert "measurements_2" not in congestion.outputs
    assert [slot.kind for slot in congestion.configuration_slots] == ["region_set"]

    wrong_way = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P05*.json")).read_text("utf-8")
    ).select_variant("video")
    lanes = next(node for node in wrong_way.nodes if node.id == "lane_regions")
    assert lanes.op == "region.manual_set@1.0"
    assert lanes.params == {"regions": []}
    majority = next(node for node in wrong_way.nodes if node.id == "lane_references")
    assert majority.op == "direction.manual_set@1.0"
    compare = next(node for node in wrong_way.nodes if node.id == "opposite")
    assert compare.op == "logic.heading_by_lane@1.0"
    draw = next(node for node in wrong_way.nodes if node.id == "draw")
    tracks = next(node for node in wrong_way.nodes if node.id == "tracks")
    headings = next(node for node in wrong_way.nodes if node.id == "headings")
    frames = next(node for node in wrong_way.nodes if node.id == "frames")
    assert draw.inputs["objects"] == "$tracks"
    assert wrong_way.outputs["objects"] == "$vehicles_in_lanes"
    assert wrong_way.outputs["tracks"] == "$tracks"
    assert "event_tracks" not in wrong_way.outputs
    assert frames.params["fps"] == 2.0
    assert tracks.params == {
        "iou_threshold": 0.35,
        "max_missing_frames": 1,
        "same_label_only": True,
        "motion_consistency": True,
        "motion_prediction": True,
        "min_direction_cosine": 0.0,
        "min_motion_pixels": 5.0,
    }
    assert headings.params["min_displacement_pixels"] == 8.0
    assert headings.params["min_displacement_box_ratio"] == 0.15
    events = next(node for node in wrong_way.nodes if node.id == "events")
    assert events.params["gap_tolerance_seconds"] == 1.1
    assert draw.params["show_labels"] is False
    assert draw.params["show_track_id"] is False
    assert draw.params["show_event_labels"] is True
    # A later motion conclusion must not be painted back onto frame 0, where
    # the tracker has not accumulated any displacement evidence yet.
    assert draw.params["event_time_window"] == "event"
    assert draw.inputs["directions"] == "$lane_references"
    slots = {slot.kind: slot for slot in wrong_way.configuration_slots}
    assert set(slots) == {"region_set", "direction_set"}
    assert slots["direction_set"].active_when_op is None
    assert majority.params == {"directions": []}


def test_illegal_parking_uses_user_editable_roi_and_ten_second_persistence():
    variant = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P07*.json")).read_text("utf-8")
    ).select_variant("video")

    region = next(node for node in variant.nodes if node.id == "no_parking_region")
    assert region.op == "region.manual@1.0"
    assert region.params["shape"] in {"rectangle", "polygon"}
    persist = next(node for node in variant.nodes if node.id == "events")
    assert persist.params["seconds"] == 10.0
    assert not any(node.op == "measure.speed@1.0" for node in variant.nodes)
    assert not any(node.id == "stationary" for node in variant.nodes)
    assert [slot.kind for slot in variant.configuration_slots] == ["region"]
    event_tracks = next(
        node for node in variant.nodes if node.op == "tracks.filter_by_events@1.0"
    )
    assert event_tracks.params["time_window"] == "whole_track"
    draw = next(node for node in variant.nodes if node.id == "draw")
    assert draw.inputs["objects"] == f"${event_tracks.id}"


@pytest.mark.parametrize("preset_id", ["P06", "P07"])
def test_region_dependent_presets_expose_manual_normalized_roi(preset_id):
    path = next((ROOT / "presets_v2").glob(f"{preset_id}*.json"))
    package = SkillPackage.model_validate_json(path.read_text("utf-8"))
    variant = package.select_variant("video")
    region = next(node for node in variant.nodes if node.op == "region.manual@1.0")
    assert region.params["shape"] in {"rectangle", "polygon"}
    assert len(region.params["points"]) >= 2
    assert all(0 <= value <= 1 for point in region.params["points"] for value in point)
    assert [slot.kind for slot in variant.configuration_slots] == ["region"]
    event_tracks = next(
        node for node in variant.nodes if node.op == "tracks.filter_by_events@1.0"
    )
    assert event_tracks.params["time_window"] == "whole_track"


def test_no_helmet_and_no_rope_are_positive_evidence_then_explicit_negation():
    expected = {
        "P09": ([0.0, 0.0, 1.0, 0.45], "source_entity"),
        "P10": ([-0.6, -0.6, 1.6, 1.2], "center_in_subject_region"),
    }
    for preset_id, (subject_region, relation_name) in expected.items():
        path = next((ROOT / "presets_v2").glob(f"{preset_id}*.json"))
        package = SkillPackage.model_validate_json(path.read_text("utf-8"))
        assert any(item.polarity == "absent" for item in package.semantic_ir.constraints)
        for variant in package.variants.values():
            crop = next(node for node in variant.nodes if node.id == "equipment_crops")
            assert crop.op == "object.crop@1.0"
            assert crop.params["subject_region"] == subject_region
            resized = next(
                node for node in variant.nodes if node.id == "equipment_crop_resized"
            )
            assert resized.op == "image.resize@1.1"
            assert resized.inputs == {"frames": "$equipment_crops"}
            assert resized.params["long_side"] == 640
            association = next(
                node for node in variant.nodes if node.id == "has_equipment"
            )
            assert association.params["relation"] == relation_name
            negation = next(node for node in variant.nodes if node.id == "missing_equipment")
            assert negation.op == "logic.not@1.0"
            expected_evidence = (
                "$equipment_evidence_hold"
                if preset_id == "P09" and variant.media_type == "video"
                else "$has_equipment"
            )
            assert negation.inputs == {"condition": expected_evidence}
            final = next(node for node in variant.nodes if node.id == "violations")
            assert final.inputs["condition"] == "$missing_equipment"


def test_no_helmet_video_tracks_subjects_and_holds_local_equipment_evidence():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P09*.json")).read_text("utf-8")
    )

    image = package.select_variant("image")
    assert not any(node.op == "temporal.hold@1.0" for node in image.nodes)
    assert next(node for node in image.nodes if node.id == "missing_equipment").inputs == {
        "condition": "$has_equipment"
    }

    video = package.select_variant("video")
    assert next(node for node in video.nodes if node.id == "subject_tracks").op == (
        "track.iou@1.0"
    )
    tracked = next(node for node in video.nodes if node.id == "tracked_subjects")
    assert tracked.op == "objects.from_tracks@1.0"
    assert next(node for node in video.nodes if node.id == "equipment_crops").inputs[
        "objects"
    ] == "$tracked_subjects"
    held = next(node for node in video.nodes if node.id == "equipment_evidence_hold")
    assert held.op == "temporal.hold@1.0"
    assert held.inputs == {"condition": "$has_equipment"}
    assert held.params == {"seconds": 1.5, "value": True}
    assert next(node for node in video.nodes if node.id == "missing_equipment").inputs == {
        "condition": "$equipment_evidence_hold"
    }


def test_no_safety_rope_uses_local_hook_position_not_relationship_words():
    path = next((ROOT / "presets_v2").glob("P10*.json"))
    package = SkillPackage.model_validate_json(path.read_text("utf-8"))

    for variant in package.variants.values():
        equipment = next(node for node in variant.nodes if node.id == "equipment_raw")
        phrases = equipment.params["targets"][0]["phrases"]
        assert phrases == ["lanyard hook", "safety hook", "safety carabiner"]
        assert all("connected" not in phrase and "attached" not in phrase for phrase in phrases)
        crop = next(node for node in variant.nodes if node.id == "equipment_crops")
        assert crop.params["subject_region"] == [-0.6, -0.6, 1.6, 1.2]
        relation = next(node for node in variant.nodes if node.id == "has_equipment")
        assert relation.params == {
            "relation": "center_in_subject_region",
            "threshold": 0.0,
            "subject_region": [-0.6, -0.6, 1.6, 0.0],
            "same_source_only": True,
        }


def test_bridge_damage_preset_does_not_invent_an_unrequested_size_filter():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P13*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        assert not any(node.op == "visual.geometry@1.0" for node in variant.nodes)
        assert variant.outputs["objects"] in {
            "$bridge_damage",
            "$confirmed_objects",
        }


def test_service_area_garbage_uses_generic_container_relative_overflow_semantics():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )

    for media_type, variant in package.variants.items():
        positive = next(node for node in variant.nodes if node.id == "garbage_raw")
        assert {
            target["label"] for target in positive.params["targets"]
        } == {"垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"}
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 3
        assert not any(node.op == "visual.geometry@1.0" for node in variant.nodes)
        assert not any(
            node.id in {"garbage_pile_above_container", "garbage_pile_not_above_container"}
            for node in variant.nodes
        )
        association = next(
            node for node in variant.nodes
            if node.id == "overflow_above_container"
        )
        assert association.inputs == {
            "subjects": "$overflow_deduplicated",
            "objects": "$garbage_containers_visible",
        }
        assert association.params["relation"] == "center_in_object_region"
        assert association.params["object_region"] == [-0.25, -0.5, 1.25, 0.4]
        assert next(
            node for node in variant.nodes if node.id == "garbage_containers"
        ).params == {
            "metric": "ios",
            "threshold": 0.5,
            "keep": "best_localization",
        }
        confirmation = next(
            node for node in variant.nodes
            if node.id == "garbage_container_confirmed"
        )
        assert confirmation.inputs == {
            "subjects": "$garbage_containers",
            "objects": "$garbage_container_evidence",
        }
        assert confirmation.params["relation"] == "source_entity"
        assert next(
            node for node in variant.nodes if node.id == "overflow_deduplicated"
        ).params == {
            "metric": "ios",
            "threshold": 0.5,
            "keep": "best_localization",
        }
        assert next(
            node for node in variant.nodes if node.id == "garbage_piles"
        ).params == {
            "metric": "ios",
            "threshold": 0.5,
            "keep": "best_localization",
        }
        pile_grounding = next(
            node for node in variant.nodes
            if node.id == "garbage_pile_full_frame_raw"
        )
        assert pile_grounding.inputs == {"frames": "$resized"}
        assert not any(
            node.id == "container_has_overflow" for node in variant.nodes
        )
        if media_type == "video":
            assert any(node.op == "track.confirm@1.0" for node in variant.nodes)


def test_service_area_garbage_tiles_small_objects_and_publishes_final_count():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )

    for media_type, variant in package.variants.items():
        assert any(node.op == "image.tile@1.1" for node in variant.nodes)
        tile = next(node for node in variant.nodes if node.op == "image.tile@1.1")
        assert tile.params["tile_width"] == 512
        assert tile.params["tile_height"] == 512
        positive = next(node for node in variant.nodes if node.id == "garbage_raw")
        labels = {item["label"] for item in positive.params["targets"]}
        phrases = {
            phrase
            for item in positive.params["targets"]
            for phrase in item["phrases"]
        }
        assert labels == {
            "垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"
        }
        assert {
            "single individual black wheeled garbage bin",
            "each separate outdoor garbage bin",
            "trash visibly protruding above the rim of a garbage bin",
            "large pile of mixed garbage bags and loose waste",
            "discarded white plastic bag on the ground",
            "group of mixed small litter pieces scattered near a garbage bin",
        } <= phrases
        assert {"trash bin", "garbage container", "waste bin"}.isdisjoint(phrases)
        assert "small litter" not in phrases
        assert "small piece of trash" not in phrases
        dedup = next(node for node in variant.nodes if node.id == "garbage")
        assert dedup.params == {
            "metric": "iou",
            "threshold": 0.5,
            "keep": "best_localization",
        }
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 3
        scattered = next(node for node in variant.nodes if node.id == "scattered_garbage")
        assert scattered.params == {"labels": ["散落垃圾"], "mode": "include"}
        assert [
            node.id for node in variant.nodes if node.op == "object.crop@1.0"
        ] == ["garbage_container_crops"]
        detection_regions = next(
            node for node in variant.nodes
            if node.id == "garbage_detection_regions"
        )
        filtered = next(
            node for node in variant.nodes
            if node.id == "garbage_in_detection_regions"
        )
        assert detection_regions.op == "region.manual_set@1.0"
        assert detection_regions.params == {"regions": []}
        assert filtered.inputs == {
            "objects": "$garbage_semantic_results",
            "regions": "$garbage_detection_regions",
        }
        assert filtered.params == {
            "membership_mode": "center",
            "overlap_threshold": 0.1,
            "keep": "inside",
            "empty_regions": "passthrough",
        }
        slot = next(
            slot for slot in variant.configuration_slots
            if slot.slot_id == "garbage_detection_regions"
        )
        assert slot.kind == "region_set"
        assert slot.required is False
        assert slot.minimum_items == 1
        assert variant.outputs["objects"] in {
            "$garbage_in_detection_regions", "$confirmed_objects"
        }
        count = next(node for node in variant.nodes if node.op == "measure.count@1.0")
        assert count.inputs["entities"] == (
            variant.outputs["objects"]
            if media_type == "image"
            else variant.outputs["tracks"]
        )
        assert count.params["scope"] == ("frame" if media_type == "image" else "unique")
        assert count.params["group_by"] == "label"
        assert variant.outputs["measurements"] == f"${count.id}"
        draw = next(node for node in variant.nodes if node.op == "output.draw@1.0")
        assert draw.inputs["measurements"] == f"${count.id}"


def test_service_area_garbage_keeps_four_visible_categories_and_grouped_measurements():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )
    expected = {"垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"}

    for variant in package.variants.values():
        grounding = next(node for node in variant.nodes if node.id == "garbage_raw")
        assert {item["label"] for item in grounding.params["targets"]} == expected
        assert variant.outputs["measurements"] == "$count"
        assert next(node for node in variant.nodes if node.id == "count").params[
            "group_by"
        ] == "label"


def test_service_area_garbage_has_no_packaging_exclusion_nodes():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        assert not any("exclusion" in node.id for node in variant.nodes)
        assert not any(
            target["label"] == "整齐包装货物"
            for node in variant.nodes
            if node.op == "rex.ground@1.1"
            for target in node.params["targets"]
        )
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 3


def test_bridge_damage_uses_one_direct_defect_grounding_without_joint_matching():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P13*.json")).read_text("utf-8")
    )

    for media_type, variant in package.variants.items():
        grounding = next(node for node in variant.nodes if node.id == "bridge_damage_raw")
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 1
        assert {target["label"] for target in grounding.params["targets"]} == {
            "裂纹", "锈蚀", "渗水", "混凝土剥落", "露筋",
        }
        assert not any(node.op == "spatial.associate@1.0" for node in variant.nodes)
        assert not any(node.op == "filter.apply@1.0" for node in variant.nodes)
        if media_type == "video":
            assert any(node.op == "track.confirm@1.0" for node in variant.nodes)


def test_bridge_damage_uses_large_overlapping_tiles_and_best_localization():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P13*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        tile = next(node for node in variant.nodes if node.op == "image.tile@1.1")
        assert tile.params == {
            "tile_width": 768,
            "tile_height": 768,
            "overlap_x": 0.25,
            "overlap_y": 0.25,
            "include_full_frame": True,
        }
        resize = next(node for node in variant.nodes if node.id == "resized")
        assert resize.params["long_side"] == 2048
        dedup = next(node for node in variant.nodes if node.id == "bridge_damage")
        assert dedup.params == {
            "metric": "ios", "threshold": 0.55, "keep": "best_localization"
        }


def test_every_preset_semantic_ledger_can_be_recompiled_by_the_generic_compiler():
    from core.preset_definitions import build_preset_definitions
    from core.semantic import SemanticNormalizer, WorkflowCompiler

    registry = build_default_registry()
    compiler = WorkflowCompiler(registry)
    for definition in build_preset_definitions():
        semantic_ir = SemanticNormalizer().normalize_ledger(
            definition.ledger, definition.instruction
        )
        package = compiler.compile(
            semantic_ir,
            original_instruction=definition.instruction,
            requested_accept=list(definition.media),
            skill_id=f"generic_{definition.skill_id}",
            display_name=definition.display_name,
        )
        assert package.input.accept
        assert validate_skill_package(package, registry) == []
