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
        "rex.ground@1.1", "objects.filter_by_label@1.0",
        "logic.any@1.0",
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
        "region.manual_set@1.0", "spatial.inside@1.0",
        "filter.apply@1.0",
    },
    "P09": {
        "spatial.associate@1.0", "logic.not@1.0", "filter.apply@1.0",
    },
    "P10": {
        "spatial.associate@1.0", "logic.not@1.0", "filter.apply@1.0",
    },
    # P11 is generated through the generic business-draft compiler: one
    # batched grounding, category selection, and optional quantity check.
    "P11": {
        "rex.ground@1.1", "objects.filter_by_label@1.0",
        "measure.count@1.0", "logic.compare@1.0",
    },
    "P12": {"track.iou@1.0", "temporal.persist@1.0"},
    "P13": {
        "rex.ground@1.1", "objects.deduplicate@1.0",
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
                # Both native semantic packages and the generic business
                # compiler make instance suppression explicit before any
                # downstream category selection or measurement.
                label_selectors = [
                    candidate for candidate in variant.nodes
                    if candidate.op == "objects.filter_by_label@1.0"
                    and candidate.inputs.get("objects") == f"${node.id}"
                ]
                assert len(consumers) == 1 or label_selectors
                if consumers:
                    assert consumers[0].params["keep"] in {
                        "first", "best_localization"
                    }
                    assert consumers[0].params["metric"] in {"ios", "iou", "instance"}


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


def test_fire_smoke_preset_uses_one_batched_semantic_grounding_per_media():
    path = next((ROOT / "presets_v2").glob("P01*.json"))
    package = SkillPackage.model_validate_json(path.read_text("utf-8"))

    for variant in package.variants.values():
        grounds = [node for node in variant.nodes if node.op == "rex.ground@1.1"]
        assert len(grounds) == 1
        assert [item["label"] for item in grounds[0].params["targets"]] == [
            "smoke", "fire"
        ]
        assert not any(
            node.op == "visual.color_fraction@1.0" for node in variant.nodes
        )
        selectors = [
            node for node in variant.nodes
            if node.op == "objects.filter_by_label@1.0"
            and node.inputs.get("objects") == f"${grounds[0].id}"
        ]
        assert {node.params["labels"][0] for node in selectors} == {"smoke", "fire"}


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
        "P09": {
            "subject": "person",
            "positive_fact": "person wearing safety helmet",
            "result_label": "未佩戴安全帽人员",
            "location_evidence": [0, 0, 1, 0.35],
        },
        "P10": {
            "subject": "worker at height",
            "positive_fact": "worker at height with safety rope or safety belt connected",
            "result_label": "未系安全绳人员",
        },
    }
    for preset_id, contract in expected.items():
        path = next((ROOT / "presets_v2").glob(f"{preset_id}*.json"))
        package = SkillPackage.model_validate_json(path.read_text("utf-8"))
        assert any(item.polarity == "absent" for item in package.semantic_ir.constraints)
        for variant in package.variants.values():
            grounds = [
                node for node in variant.nodes if node.op == "rex.ground@1.1"
            ]
            assert len(grounds) == 1
            phrases = {
                phrase
                for target in grounds[0].params["targets"]
                for phrase in target["phrases"]
            }
            assert {contract["subject"], contract["positive_fact"]} <= phrases
            if preset_id == "P09":
                assert [
                    phrase
                    for target in grounds[0].params["targets"]
                    for phrase in target["phrases"]
                ] == [
                    "safety helmet",
                    "person wearing safety helmet",
                    "person",
                ]

            dedup = next(
                node
                for node in variant.nodes
                if node.op == "objects.deduplicate@1.0"
            )
            assert dedup.inputs == {"objects": f"${grounds[0].id}"}
            assert dedup.params == {
                "metric": "instance",
                "threshold": 0.45,
                "keep": "best_localization",
            }

            semantic_association = next(
                node for node in variant.nodes if node.op == "spatial.associate@1.0"
                and node.params.get("relation") == "mutual_match"
            )
            assert semantic_association.params == {
                "relation": "mutual_match", "threshold": 0.5
            }
            evidence = semantic_association.id
            if "location_evidence" in contract:
                location_association = next(
                    node
                    for node in variant.nodes
                    if node.op == "spatial.associate@1.0"
                    and node.params.get("relation") == "center_in_subject_region"
                )
                assert location_association.params["subject_region"] == contract[
                    "location_evidence"
                ]
                positive_fact = next(
                    node
                    for node in variant.nodes
                    if node.op == "logic.all@1.0"
                    and node.params.get("combine_scope") == "by_key"
                )
                assert positive_fact.inputs["conditions"] == [
                    f"${semantic_association.id}",
                    f"${location_association.id}",
                ]
                evidence = positive_fact.id
            negation = next(
                node for node in variant.nodes if node.op == "logic.not@1.0"
            )
            assert negation.op == "logic.not@1.0"
            assert negation.inputs == {"condition": f"${evidence}"}
            final = next(
                node
                for node in variant.nodes
                if node.op == "filter.apply@1.0"
                and node.inputs.get("condition") == f"${negation.id}"
            )
            result = next(
                node
                for node in variant.nodes
                if node.op == "objects.relabel@1.0"
                and node.inputs == {"objects": f"${final.id}"}
            )
            assert result.params["label"] == contract["result_label"]
            assert not any(
                node.op
                in {
                    "object.crop@1.0",
                    "track.iou@1.0",
                    "track.confirm@1.0",
                    "temporal.hold@1.0",
                }
                for node in variant.nodes
            )


def test_bridge_damage_preset_does_not_invent_an_unrequested_size_filter():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P13*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        assert not any(node.op == "visual.geometry@1.0" for node in variant.nodes)
        assert variant.outputs["objects"] == "$candidates"


def test_service_area_garbage_uses_generic_multi_target_business_orchestration():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        ground = next(node for node in variant.nodes if node.op == "rex.ground@1.1")
        assert {target["label"] for target in ground.params["targets"]} == {
            "垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"
        }
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 1
        assert not any(node.op == "spatial.associate@1.0" for node in variant.nodes)
        assert not any(node.op == "object.crop@1.0" for node in variant.nodes)


def test_service_area_garbage_selects_all_categories_and_publishes_grouped_count():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        ground = next(node for node in variant.nodes if node.op == "rex.ground@1.1")
        deduplicated = next(
            node for node in variant.nodes if node.op == "objects.deduplicate@1.0"
        )
        selector = next(
            node for node in variant.nodes if node.op == "objects.filter_by_label@1.0"
        )
        assert deduplicated.inputs == {"objects": f"${ground.id}"}
        assert deduplicated.params == {
            "metric": "instance",
            "threshold": 0.45,
            "keep": "best_localization",
        }
        assert selector.inputs == {"objects": f"${deduplicated.id}"}
        assert set(selector.params["labels"]) == {
            "垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"
        }
        count = next(node for node in variant.nodes if node.op == "measure.count@1.0")
        assert count.params["group_by"] == "label"
        assert any(value == f"${count.id}" for value in variant.outputs.values())
        assert variant.outputs["objects"] == f"${selector.id}"


def test_service_area_garbage_keeps_four_visible_categories_and_grouped_measurements():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P11*.json")).read_text("utf-8")
    )
    expected = {"垃圾容器", "溢出垃圾", "垃圾堆", "散落垃圾"}

    for variant in package.variants.values():
        grounding = next(node for node in variant.nodes if node.op == "rex.ground@1.1")
        assert {item["label"] for item in grounding.params["targets"]} == expected
        assert next(node for node in variant.nodes if node.op == "measure.count@1.0").params[
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
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 1


def test_bridge_damage_uses_one_direct_defect_grounding_without_joint_matching():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P13*.json")).read_text("utf-8")
    )

    for media_type, variant in package.variants.items():
        grounding = next(node for node in variant.nodes if node.id == "candidates_raw")
        assert sum(node.op == "rex.ground@1.1" for node in variant.nodes) == 1
        assert {target["label"] for target in grounding.params["targets"]} == {
            "裂纹", "锈蚀", "渗水", "混凝土剥落", "露筋",
        }
        assert not any(node.op == "spatial.associate@1.0" for node in variant.nodes)
        assert not any(node.op == "filter.apply@1.0" for node in variant.nodes)
        assert grounding.params["phrase_selection"] == "primary_per_target"


def test_bridge_damage_uses_generic_single_pass_grounding_and_instance_deduplication():
    package = SkillPackage.model_validate_json(
        next((ROOT / "presets_v2").glob("P13*.json")).read_text("utf-8")
    )

    for variant in package.variants.values():
        assert not any(node.op == "image.tile@1.1" for node in variant.nodes)
        dedup = next(node for node in variant.nodes if node.id == "candidates")
        assert dedup.params == {
            "metric": "instance", "threshold": 0.45, "keep": "best_localization"
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
