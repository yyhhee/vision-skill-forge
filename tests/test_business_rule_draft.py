from __future__ import annotations

import pytest

from core.business_capabilities import build_business_capability_registry
from core.business_result_projector import build_runtime_contract
from core.business_rule_draft import (
    BusinessDraftError,
    NaturalLanguageBusinessDraft,
    apply_business_rule_draft,
    normalize_business_draft_payload,
)
from core.editor_generation import build_editor_document
from core.editor_generation import resolve_pending_decision
from core.editor_service import EditorService
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler


def _base(requested=("image",)):
    registry = build_default_registry()
    semantic = CanonicalSemanticIR.model_validate(
        {
            "mode": "direct_grounding",
            "target": {
                "concept": "person",
                "source_span": "人",
                "phrases": ["person"],
            },
            "constraints": [],
            "logic": "all",
            "unresolved": [],
            "semantic_hash": "c" * 64,
        }
    )
    package = WorkflowCompiler(registry).compile(
        semantic,
        original_instruction="测试业务草稿",
        requested_accept=list(requested),
        skill_id="business_draft_fixture",
        display_name="业务草稿测试",
    )
    return registry, build_editor_document(package), package


def _image_draft():
    return {
        "schema_version": "1.0",
        "media_requirement": "image",
        "branches": [
            {
                "key": "clothes",
                "name": "指定着装人员",
                "media_type": "image",
                "conditions": [
                    {
                        "key": "people",
                        "name": "检测人员",
                        "capability_id": "target.detect",
                        "parameters": {
                            "targets": ["person"],
                            "phrases": "person",
                            "business_label": "人员",
                        },
                    },
                    {
                        "key": "red",
                        "name": "红色上衣",
                        "capability_id": "attribute.color",
                        "parameters": {
                            "source": "condition:people",
                            "part": "upper_clothing",
                            "color": "red",
                        },
                    },
                    {
                        "key": "gray",
                        "name": "灰色裤子",
                        "capability_id": "attribute.color",
                        "parameters": {
                            "source": "condition:people",
                            "part": "lower_clothing",
                            "color": "gray",
                        },
                    },
                    {
                        "key": "same",
                        "name": "同一人员同时满足着装",
                        "capability_id": "subject.same_attributes",
                        "parameters": {
                            "subject": "condition:people",
                            "attributes": ["condition:red", "condition:gray"],
                        },
                    },
                ],
            },
            {
                "key": "people_count",
                "name": "人员数量",
                "media_type": "image",
                "conditions": [
                    {
                        "key": "people2",
                        "name": "检测人员",
                        "capability_id": "target.detect",
                        "parameters": {"targets": ["person"], "phrases": "person"},
                    },
                    {
                        "key": "count",
                        "name": "人数大于2",
                        "capability_id": "measure.count",
                        "parameters": {
                            "source": "condition:people2",
                            "scope": "full_frame",
                            "operator": ">",
                            "threshold": 2,
                        },
                    },
                ],
            },
        ],
        "final_decision": {
            "name": "多区域人员告警",
            "source_refs": ["branch:clothes", "branch:people_count"],
            "combination": "AND",
        },
        "results": [
            {
                "key": "clothed_people",
                "name": "红色上衣、灰色裤子人员",
                "source_ref": "condition:clothes.same",
                "result_kind": "entities",
                "evidence_policy": "required",
            },
            {
                "key": "people_count",
                "name": "人员数量",
                "source_ref": "condition:people_count.count",
                "result_kind": "count",
            },
            {
                "key": "decision",
                "name": "多区域人员告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
            },
        ],
    }


def test_llm_business_draft_becomes_the_single_compilable_editor_document():
    registry, document, _ = _base()
    converted = apply_business_rule_draft(
        document,
        _image_draft(),
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )

    assert [item.display_name for item in converted.skill_template.business_branches] == [
        "\u6307\u5b9a\u7740\u88c5\u4eba\u5458",
        "\u4eba\u5458\u6570\u91cf",
    ]
    assert converted.skill_template.final_decision.source_refs == [
        "branch:branch_clothes",
        "branch:branch_people_count",
    ]
    compiled = EditorService(registry).apply(converted)
    assert compiled.validation_report["can_run"] is True
    assert "final_primary" in compiled.effective_skill_package.variants["image"].outputs


def test_missing_same_subject_is_repaired_and_drives_entity_result_drawing():
    registry, document, _ = _base()
    draft = _image_draft()
    clothes = draft["branches"][0]
    clothes["conditions"] = clothes["conditions"][:3]
    draft["branches"] = [clothes]
    draft["final_decision"] = {
        "name": "红色上衣灰色裤子人员",
        "decision_type": "detection_summary",
        "source_refs": ["branch:clothes"],
        "combination": "AND",
    }
    draft["results"] = [{
        "key": "clothed_people",
        "name": "红色上衣、灰色裤子人员",
        "source_ref": "final:primary",
        "result_kind": "entities",
        "evidence_policy": "required",
    }]

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    atoms = converted.skill_template.business_branches[0].condition_root.children
    same = next(
        item for item in atoms
        if item.capability_id == "subject.same_attributes"
    )
    entity_result = converted.skill_template.result_specs[0]
    assert same.parameters["attributes"] == [
        "condition:condition_clothes_red",
        "condition:condition_clothes_gray",
    ]
    assert entity_result.source_ref == f"condition:{same.expression_id}"

    compiled = EditorService(registry).apply(converted)
    variant = compiled.effective_skill_package.variants["image"]
    nodes = {node.id: node for node in variant.nodes}
    object_node = nodes[variant.outputs["objects"].removeprefix("$")]
    draw = next(node for node in variant.nodes if node.op == "output.draw@1.0")
    assert object_node.op == "set.semi_join@1.0"
    assert draw.inputs["objects"] == variant.outputs["objects"]


def test_same_subject_repair_is_capability_generic_but_respects_or_semantics():
    registry, document, _ = _base()
    draft = _image_draft()
    clothes = draft["branches"][0]
    clothes["conditions"] = clothes["conditions"][:2]
    clothes["conditions"].append(
        {
            "key": "large",
            "name": "尺寸较大",
            "capability_id": "attribute.geometry",
            "parameters": {
                "source": "condition:people",
                "dimension": "size",
                "operator": ">=",
                "threshold": 10,
            },
        }
    )
    clothes["logic"] = "OR"
    draft["branches"] = [clothes]
    draft["final_decision"] = {
        "name": "红衣或大目标",
        "decision_type": "detection_summary",
        "source_refs": ["branch:clothes"],
        "combination": "OR",
    }
    draft["results"] = [{
        "key": "matches",
        "name": "匹配目标",
        "source_ref": "branch:clothes",
        "result_kind": "entities",
    }]

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    atoms = converted.skill_template.business_branches[0].condition_root.children
    assert not any(
        item.capability_id == "subject.same_attributes" for item in atoms
    )


def test_same_subject_repair_supports_different_attribute_capabilities():
    registry, document, _ = _base()
    draft = _image_draft()
    clothes = draft["branches"][0]
    clothes["conditions"] = clothes["conditions"][:2]
    clothes["conditions"].append(
        {
            "key": "large",
            "name": "尺寸较大",
            "capability_id": "attribute.geometry",
            "parameters": {
                "source": "condition:people",
                "dimension": "size",
                "operator": ">=",
                "threshold": 10,
            },
        }
    )
    draft["branches"] = [clothes]
    draft["final_decision"] = {
        "name": "红色且尺寸较大的人员",
        "decision_type": "detection_summary",
        "source_refs": ["branch:clothes"],
        "combination": "AND",
    }
    draft["results"] = [{
        "key": "matches",
        "name": "匹配人员",
        "source_ref": "branch:clothes",
        "result_kind": "entities",
    }]

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    same = next(
        item
        for item in converted.skill_template.business_branches[0].condition_root.children
        if item.capability_id == "subject.same_attributes"
    )
    assert same.parameters["attributes"] == [
        "condition:condition_clothes_red",
        "condition:condition_clothes_large",
    ]


def test_harmless_llm_business_json_shape_noise_is_normalized():
    draft = _image_draft()
    draft["final_decision"]["key"] = "singleton_final"
    draft["final_decision"]["source_refs"] *= 2
    draft["trigger_policy"] = {"mode": "on_match"}
    draft["branches"][0]["conditions"][0]["children"] = None

    normalized = normalize_business_draft_payload(draft)
    validated = NaturalLanguageBusinessDraft.model_validate(normalized)

    assert "key" not in normalized["final_decision"]
    assert normalized["final_decision"]["source_refs"] == [
        "branch:clothes", "branch:people_count"
    ]
    assert normalized["trigger_policy"]["mode"] == "once"
    assert validated.branches[0].conditions[0].children == []


def test_unique_condition_result_reference_recovers_a_stale_branch_prefix():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["results"][0]["source_ref"] = "condition:stale_branch.red"

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )

    assert converted.skill_template.result_specs[0].source_ref == (
        "condition:condition_clothes_red"
    )


def test_missing_equipment_descriptor_materializes_visible_evidence():
    registry, document, _ = _base()
    draft = {
        "schema_version": "1.0",
        "media_requirement": "image",
        "branches": [{
            "key": "ppe",
            "name": "缺少必要装备",
            "media_type": "image",
            "conditions": [
                {
                    "key": "people",
                    "name": "检测人员",
                    "capability_id": "target.detect",
                    "parameters": {"targets": ["person"], "phrases": "person"},
                },
                {
                    "key": "missing",
                    "name": "人员缺少必要装备",
                    "capability_id": "subject.missing_equipment",
                    "parameters": {
                        "subject": ["condition:people"],
                        "equipment": ["safety_helmet"],
                    },
                },
            ],
        }],
        "final_decision": {
            "name": "存在缺少装备人员",
            "decision_type": "detection_summary",
            "source_refs": ["branch:ppe"],
            "combination": "AND",
        },
        "results": [{
            "key": "violators",
            "name": "缺少装备人员",
            "source_ref": "branch:ppe",
            "result_kind": "entities",
        }],
    }

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    atoms = converted.skill_template.business_branches[0].condition_root.children
    missing = next(
        item for item in atoms
        if item.capability_id == "subject.missing_equipment"
    )
    equipment = next(
        item for item in atoms
        if item.capability_id == "target.detect" and item is not atoms[0]
    )
    assert missing.parameters["subject"] == "condition:condition_ppe_people"
    assert missing.parameters["equipment"] == f"condition:{equipment.expression_id}"

    compiled = EditorService(registry).apply(converted)
    assert any(
        node.op == "set.anti_join@1.0"
        for node in compiled.effective_skill_package.variants["image"].nodes
    )


def test_single_source_lists_and_display_units_do_not_break_video_conditions():
    registry, document, _ = _base(("video",))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "video",
        "branches": [{
            "key": "slow_vehicle",
            "name": "低速车辆",
            "media_type": "video",
            "conditions": [
                {
                    "key": "vehicles",
                    "name": "检测车辆",
                    "capability_id": "target.detect",
                    "parameters": {"targets": ["vehicle"], "phrases": "vehicle"},
                },
                {
                    "key": "tracks",
                    "name": "创建车辆轨迹",
                    "capability_id": "motion.track",
                    "parameters": {"source": ["condition:vehicles"]},
                },
                {
                    "key": "speed",
                    "name": "速度低于2",
                    "capability_id": "motion.speed",
                    "parameters": {
                        "source": ["condition:tracks"],
                        "scope": "full_frame",
                        "operator": "<",
                        "threshold": 2,
                        "unit": "px/s",
                        "aggregation": "per_track",
                    },
                },
                {
                    "key": "duplicate_time",
                    "name": "持续1秒",
                    "capability_id": "state.current",
                    "parameters": {
                        "source": "condition:speed",
                        "scope": "full_frame",
                        "duration_seconds": 1,
                    },
                },
            ],
            "time": {"mode": "continuous", "duration_seconds": 1},
        }],
        "final_decision": {
            "name": "低速车辆持续出现",
            "decision_type": "event_decision",
            "source_refs": ["branch:slow_vehicle"],
            "combination": "AND",
        },
        "results": [{
            "key": "decision",
            "name": "低速车辆事件",
            "source_ref": "final:primary",
            "result_kind": "decision",
        }],
    }

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["video"],
    )
    children = converted.skill_template.business_branches[0].condition_root.children
    speed = children[2]
    assert speed.parameters["source"] == "condition:condition_slow_vehicle_tracks"
    assert speed.parameters["motion_state"] == "speed"
    assert "unit" not in speed.parameters
    assert not any(item.expression_id.endswith("duplicate_time") for item in children)
    assert EditorService(registry).apply(converted).validation_report["can_run"] is True


def test_video_speed_condition_inserts_required_track_stage():
    registry, document, _ = _base(("video",))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "video",
        "branches": [{
            "key": "slow_vehicle",
            "name": "低速车辆",
            "media_type": "video",
            "conditions": [
                {
                    "key": "vehicles",
                    "name": "检测车辆",
                    "capability_id": "target.detect",
                    "parameters": {"targets": ["vehicle"], "phrases": ["vehicle"]},
                },
                {
                    "key": "speed",
                    "name": "速度低于2",
                    "capability_id": "motion.speed",
                    "parameters": {
                        "source": "condition:slow_vehicle.vehicles",
                        "operator": "<",
                        "threshold": 2,
                    },
                },
            ],
            "time": {"mode": "continuous", "duration_seconds": 10},
        }],
        "final_decision": {
            "name": "低速车辆持续出现",
            "decision_type": "event_decision",
            "source_refs": ["branch:slow_vehicle"],
            "combination": "AND",
        },
        "results": [{
            "key": "decision",
            "name": "低速车辆事件",
            "source_ref": "final:primary",
            "result_kind": "decision",
        }],
    }

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["video"],
    )
    children = converted.skill_template.business_branches[0].condition_root.children
    assert [item.capability_id for item in children] == [
        "target.detect", "motion.track", "motion.speed"
    ]
    assert children[2].parameters["source"] == f"condition:{children[1].expression_id}"
    assert EditorService(registry).apply(converted).validation_report["can_run"] is True


def test_inline_visible_state_becomes_same_subject_entity_evidence():
    registry, document, _ = _base(("video",))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "video",
        "branches": [{
            "key": "pose",
            "name": "倒地人员",
            "media_type": "video",
            "conditions": [
                {
                    "key": "people",
                    "name": "检测人员",
                    "capability_id": "target.detect",
                    "parameters": {"targets": "person", "phrases": ["person"]},
                },
                {
                    "key": "fallen",
                    "name": "摔倒或躺地姿态",
                    "capability_id": "state.current",
                    "parameters": {
                        "source": "condition:pose.people",
                        "state": "falling_or_lying_on_ground",
                    },
                },
                {
                    "key": "same",
                    "name": "同一人员满足姿态",
                    "capability_id": "subject.same_attributes",
                    "parameters": {
                        "subject": "condition:pose.people",
                        "attributes": ["condition:pose.fallen"],
                    },
                },
            ],
            "time": {
                "mode": "continuous",
                "duration_seconds": 1,
                "identity_scope": "track",
            },
        }],
        "final_decision": {
            "name": "倒地事件",
            "decision_type": "event_decision",
            "source_refs": ["branch:pose"],
            "combination": "AND",
        },
        "results": [{
            "key": "events",
            "name": "倒地事件",
            "source_ref": "branch:pose",
            "result_kind": "events",
        }],
    }

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["video"],
    )
    atoms = converted.skill_template.business_branches[0].condition_root.children
    fallen = next(item for item in atoms if item.expression_id.endswith("_fallen"))
    assert fallen.capability_id == "target.detect"
    assert fallen.parameters["targets"][0]["phrases"] == [
        "person falling or lying on ground"
    ]
    compiled = EditorService(registry).apply(converted)
    assert any(
        node.op == "set.semi_join@1.0"
        for node in compiled.effective_skill_package.variants["video"].nodes
    )


def test_plain_attribute_descriptions_are_bound_to_typed_evidence_conditions():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["branches"][0]["conditions"][3]["parameters"]["attributes"] = [
        "red upper_clothing",
        "gray lower_clothing",
    ]

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    same = next(
        expression
        for expression in converted.skill_template.business_branches[0].condition_root.children
        if expression.capability_id == "subject.same_attributes"
    )
    assert same.parameters["attributes"] == [
        "condition:condition_clothes_red",
        "condition:condition_clothes_gray",
    ]

    compiled = EditorService(registry).apply(converted)
    assert compiled.validation_report["can_run"] is True


def test_chinese_attribute_descriptions_are_bound_by_condition_name():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["branches"][0]["conditions"][3]["parameters"]["attributes"] = [
        "红色上衣",
        "灰色裤子",
    ]

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    same = next(
        expression
        for expression in converted.skill_template.business_branches[0].condition_root.children
        if expression.capability_id == "subject.same_attributes"
    )
    assert same.parameters["attributes"] == [
        "condition:condition_clothes_red",
        "condition:condition_clothes_gray",
    ]


def test_membership_is_chained_after_same_subject_attributes():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["resources"] = [
        {
            "key": "region1",
            "name": "区域1",
            "resource_type": "region",
            "semantic_role": "region1",
            "media_types": ["image"],
        }
    ]
    draft["branches"][0]["conditions"].append(
        {
            "key": "inside",
            "name": "区域1内",
            "capability_id": "spatial.membership",
            "parameters": {
                "source": "condition:people",
                "scope": "resource:region1",
            },
        }
    )

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )

    atoms = converted.skill_template.business_branches[0].condition_root.children
    same = next(item for item in atoms if item.capability_id == "subject.same_attributes")
    membership = next(item for item in atoms if item.capability_id == "spatial.membership")
    assert membership.parameters["source"] == f"condition:{same.expression_id}"


def test_target_detect_scope_is_lifted_to_a_membership_condition():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["resources"] = [
        {
            "key": "region1",
            "name": "区域1",
            "resource_type": "region",
            "semantic_role": "region1",
            "media_types": ["image"],
        }
    ]
    draft["branches"][0]["conditions"][0]["parameters"]["scope"] = (
        "resource:region1"
    )

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    atoms = converted.skill_template.business_branches[0].condition_root.children
    detect = next(item for item in atoms if item.capability_id == "target.detect")
    membership = next(
        item for item in atoms if item.capability_id == "spatial.membership"
    )
    same = next(
        item for item in atoms if item.capability_id == "subject.same_attributes"
    )

    assert "scope" not in detect.parameters
    assert membership.parameters["scope"] == "resource_region1"
    assert membership.parameters["source"] == f"condition:{same.expression_id}"


def test_llm_parameter_aliases_and_ratios_are_normalized_to_editor_schema():
    registry, document, _ = _base()
    draft = _image_draft()
    red = draft["branches"][0]["conditions"][1]
    red["parameters"].update(
        {"part": "upper_body_clothing", "minimum_fraction": 0.5}
    )
    count = draft["branches"][1]["conditions"][1]
    count["parameters"].update(
        {"group_by": "named_region", "operator": "greater_than"}
    )
    draft["resources"] = [
        {
            "key": "region1",
            "name": "区域1",
            "resource_type": "region",
            "semantic_role": "region1",
            "media_types": ["image"],
        }
    ]
    draft["branches"][0]["conditions"].append(
        {
            "key": "inside",
            "name": "区域1内",
            "capability_id": "spatial.membership",
            "parameters": {
                "source": "condition:people",
                "scope": "resource:region1",
                "membership": "inside",
                "minimum_overlap": 0.8,
                "inside": "inside",
            },
        }
    )

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    atoms = converted.skill_template.business_branches[0].condition_root.children
    red_atom = next(item for item in atoms if item.display_name == "红色上衣")
    region_atom = next(item for item in atoms if item.display_name == "区域1内")
    count_atom = converted.skill_template.business_branches[1].condition_root.children[1]

    assert red_atom.parameters["part"] == "upper_clothing"
    assert red_atom.parameters["minimum_fraction"] == 50.0
    assert region_atom.parameters["membership"] == "center"
    assert region_atom.parameters["minimum_overlap"] == 80.0
    assert region_atom.parameters["inside"] is True
    assert count_atom.parameters["group_by"] == "region"
    assert count_atom.parameters["operator"] == ">"


def test_final_result_name_can_be_pinned_to_the_user_confirmed_skill_name():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["final_decision"]["name"] = "LLM 临时名称"

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
        final_display_name="多区域人员告警",
    )

    assert converted.skill_template.final_decision.display_name == "多区域人员告警"


def test_full_frame_cannot_masquerade_as_a_typed_count_source():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["branches"][1]["conditions"][1]["parameters"]["source"] = "full_frame"

    with pytest.raises(ValueError, match="full_frame 只能用于 scope"):
        apply_business_rule_draft(
            document,
            draft,
            build_business_capability_registry(registry),
            requested_accept=["image"],
        )


def test_declaring_both_media_requires_reviewable_image_and_video_flows():
    registry, document, _ = _base(("image", "video"))
    draft = _image_draft()
    draft["media_requirement"] = "both"

    with pytest.raises(ValueError, match="必须生成"):
        apply_business_rule_draft(
            document,
            draft,
            build_business_capability_registry(registry),
            requested_accept=["image", "video"],
        )


def test_complex_pattern_cannot_join_image_and_video_variants():
    draft = _image_draft()
    video_branch = draft["branches"][1].copy()
    video_branch["key"] = "video_people_count"
    video_branch["media_type"] = "video"
    draft["branches"].append(video_branch)
    draft["media_requirement"] = "both"
    draft["patterns"] = [
        {
            "key": "cross_media",
            "name": "错误跨媒体组合",
            "media_type": "video",
            "mode": "all_active",
            "branch_keys": ["clothes", "video_people_count"],
        }
    ]

    with pytest.raises(ValueError, match="只能引用同一视频流程"):
        NaturalLanguageBusinessDraft.model_validate(draft)


def test_image_branch_cannot_hide_a_continuous_time_qualifier():
    draft = _image_draft()
    draft["branches"][0]["time"] = {
        "mode": "continuous",
        "duration_seconds": 1,
    }

    with pytest.raises(ValueError, match="图片分支.*只能立即判断"):
        NaturalLanguageBusinessDraft.model_validate(draft)


def test_media_conflict_is_a_business_error_before_atomic_compilation():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["branches"][0]["conditions"].append(
        {
            "key": "wrong_way",
            "name": "����",
            "capability_id": "motion.wrong_way",
            "parameters": {
                "source": "condition:people",
                "scope": "full_frame",
                "reference": "resource:direction",
            },
        }
    )
    with pytest.raises(ValueError, match="\u4ec5\u89c6\u9891\u80fd\u529b"):
        apply_business_rule_draft(
            document,
            draft,
            build_business_capability_registry(registry),
            requested_accept=["image"],
        )


def test_unresolved_quantity_is_preserved_as_review_work_not_json_failure():
    registry, document, _ = _base()
    draft = _image_draft()
    draft["pending_decisions"] = [
        {
            "key": "people_threshold",
            "kind": "count_threshold",
            "prompt": "人员数量阈值是多少？",
            "reason": "用户只说了大于等于，未提供数值",
            "recommended_value": 1,
            "affected_refs": ["condition:people_count.count"],
            "required_before": "run",
        }
    ]
    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    pending = converted.skill_template.pending_decisions[0]
    assert pending.parameter_kind == "count_threshold"
    assert pending.resolution.state == "unresolved"
    assert pending.resolution.required_before == "run"

    resolved = resolve_pending_decision(converted, pending.decision_id, 3)
    count_branch = next(
        item
        for item in resolved.skill_template.business_branches
        if item.branch_id == "branch_people_count"
    )
    count_condition = next(
        item
        for item in count_branch.condition_root.children
        if item.expression_id == "condition_people_count_count"
    )
    assert count_condition.parameters["threshold"] == 3
    assert pending.decision_id not in [
        item.decision_id
        for item in resolved.skill_template.pending_decisions
        if item.resolution.state == "unresolved"
    ]


def test_both_media_skill_compiles_independent_variants_but_each_run_stays_single_media():
    registry, document, _ = _base(("image", "video"))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "both",
        "branches": [
            {
                "key": "image_people",
                "name": "图片人员",
                "media_type": "image",
                "conditions": [
                    {
                        "key": "people",
                        "name": "检测人员",
                        "capability_id": "target.detect",
                        "parameters": {"targets": ["person"], "phrases": "person"},
                    }
                ],
            },
            {
                "key": "video_vehicle",
                "name": "视频车辆持续出现",
                "media_type": "video",
                "conditions": [
                    {
                        "key": "vehicle",
                        "name": "检测车辆",
                        "capability_id": "target.detect",
                        "parameters": {"targets": ["vehicle"], "phrases": "vehicle"},
                    }
                ],
                "time": {
                    "mode": "continuous",
                    "duration_seconds": 2,
                    "identity_scope": "global",
                },
            },
            {
                "key": "video_smoke",
                "name": "随后出现烟火",
                "media_type": "video",
                "conditions": [
                    {
                        "key": "smoke",
                        "name": "检测烟火",
                        "capability_id": "target.detect",
                        "parameters": {"targets": ["smoke"], "phrases": "smoke"},
                    }
                ],
            },
        ],
        "patterns": [
            {
                "key": "vehicle_then_smoke",
                "name": "车辆持续后出现烟火",
                "media_type": "video",
                "mode": "sequence",
                "branch_keys": ["video_vehicle", "video_smoke"],
                "window_seconds": 10,
            }
        ],
        "final_decision": {
            "name": "当前媒体目标告警",
            "source_refs": ["branch:image_people", "event:vehicle_then_smoke"],
            "combination": "AND",
        },
        "results": [
            {
                "key": "image_people",
                "name": "图片人员框",
                "source_ref": "condition:image_people.people",
                "result_kind": "entities",
            },
            {
                "key": "video_events",
                "name": "视频持续事件",
                "source_ref": "event:vehicle_then_smoke",
                "result_kind": "events",
            },
            {
                "key": "decision",
                "name": "当前媒体目标告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
            },
        ],
    }
    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image", "video"],
    )
    compiled = EditorService(registry).apply(converted)

    assert set(compiled.effective_skill_package.input.accept) == {"image", "video"}
    assert compiled.skill_template.final_decision.media_source_refs == {
        "image": ["branch:branch_image_people"],
        "video": ["event:pattern_vehicle_then_smoke"],
    }
    image_variant = compiled.effective_skill_package.variants["image"]
    video_variant = compiled.effective_skill_package.variants["video"]
    assert "final_primary" in image_variant.outputs
    assert "final_primary" in video_variant.outputs
    assert not any(item.op == "temporal.qualify@1.0" for item in image_variant.nodes)
    assert not any(item.op == "temporal.sequence@2.0" for item in image_variant.nodes)
    assert any(item.op == "temporal.qualify@1.0" for item in video_variant.nodes)
    assert any(item.op == "temporal.sequence@2.0" for item in video_variant.nodes)

    image_contract = build_runtime_contract(compiled, "image")
    video_contract = build_runtime_contract(compiled, "video")
    assert [item["display_name"] for item in image_contract["result_specs"]] == [
        "图片人员框",
        "当前媒体目标告警",
    ]
    assert [item["display_name"] for item in video_contract["result_specs"]] == [
        "视频持续事件",
        "当前媒体目标告警",
    ]
    assert image_contract["final_decision"]["source_refs"] == [
        "branch:branch_image_people"
    ]
    assert video_contract["final_decision"]["source_refs"] == [
        "event:pattern_vehicle_then_smoke"
    ]


def test_llm_draft_supports_recursive_and_or_not_without_atomic_graph_output():
    registry, document, _ = _base()
    draft = {
        "schema_version": "1.0",
        "media_requirement": "image",
        "branches": [
            {
                "key": "mixed_targets",
                "name": "人员或非车辆",
                "media_type": "image",
                "conditions": [
                    {
                        "key": "choice",
                        "name": "人员或非车辆条件组",
                        "operator": "OR",
                        "children": [
                            {
                                "key": "people",
                                "name": "检测人员",
                                "operator": "ATOM",
                                "capability_id": "target.detect",
                                "parameters": {
                                    "targets": ["person"],
                                    "phrases": "person",
                                },
                            },
                            {
                                "key": "not_vehicle",
                                "name": "不是车辆",
                                "operator": "NOT",
                                "children": [
                                    {
                                        "key": "vehicle",
                                        "name": "检测车辆",
                                        "operator": "ATOM",
                                        "capability_id": "target.detect",
                                        "parameters": {
                                            "targets": ["vehicle"],
                                            "phrases": "vehicle",
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            }
        ],
        "final_decision": {
            "name": "组合条件结果",
            "source_refs": ["branch:mixed_targets"],
        },
        "results": [
            {
                "key": "decision",
                "name": "组合条件结果",
                "source_ref": "final:primary",
                "result_kind": "decision",
            }
        ],
    }
    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    root = converted.skill_template.business_branches[0].condition_root
    assert root.operator == "OR"
    assert root.children[1].operator == "NOT"

    compiled = EditorService(registry).apply(converted)
    operators = {
        item.op for item in compiled.effective_skill_package.variants["image"].nodes
    }
    assert "logic.any@1.0" in operators
    assert "logic.not@1.0" in operators


def test_track_identity_repairs_temporal_placeholder_and_one_branch_pattern():
    registry, document, _ = _base(("video",))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "video",
        "branches": [{
            "key": "loitering",
            "name": "人员逗留",
            "media_type": "video",
            "conditions": [
                {
                    "key": "people",
                    "name": "检测人员",
                    "capability_id": "target.detect",
                    "parameters": {"targets": ["person"], "phrases": ["person"]},
                },
                {
                    "key": "inside",
                    "name": "位于区域",
                    "capability_id": "spatial.membership",
                    "parameters": {
                        "source": "condition:loitering.people",
                        "scope": "resource:area",
                        "inside": True,
                    },
                },
                {
                    "key": "duplicate_time",
                    "name": "持续1秒",
                    "capability_id": "state.current",
                    "parameters": {
                        "source": "condition:loitering.inside",
                        "scope": "resource:area",
                    },
                },
            ],
            "time": {
                "mode": "continuous",
                "duration_seconds": 1,
                "identity_scope": "track",
            },
        }],
        "resources": [{
            "key": "area",
            "name": "区域",
            "resource_type": "region",
            "semantic_role": "area",
            "media_types": ["video"],
        }],
        "patterns": [{
            "key": "redundant_pattern",
            "name": "单分支持续",
            "media_type": "video",
            "mode": "all_completed_within_window",
            "branch_keys": ["loitering"],
            "window_seconds": 1,
        }],
        "final_decision": {
            "name": "人员逗留",
            "source_refs": ["event:redundant_pattern"],
        },
        "results": [{
            "key": "tracks",
            "name": "人员轨迹",
            "source_ref": "branch:loitering",
            "result_kind": "tracks",
        }],
    }

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["video"],
    )
    children = converted.skill_template.business_branches[0].condition_root.children
    assert [item.capability_id for item in children] == [
        "target.detect", "motion.track", "spatial.membership"
    ]
    assert converted.skill_template.event_patterns == []
    assert converted.skill_template.final_decision.source_refs == [
        "branch:branch_loitering"
    ]
    track_id = children[1].expression_id
    assert converted.skill_template.result_specs[0].source_ref == f"condition:{track_id}"
    compiled = EditorService(registry).apply(converted)
    assert compiled.effective_skill_package is not None
    assert compiled.validation_report["can_run"] is False


def test_visible_state_without_declared_subject_becomes_direct_detection():
    registry, document, _ = _base(("image",))
    draft = {
        "schema_version": "1.0",
        "media_requirement": "image",
        "branches": [{
            "key": "accident",
            "name": "事故车辆",
            "media_type": "image",
            "conditions": [{
                "key": "collision",
                "name": "车辆碰撞",
                "capability_id": "state.current",
                "parameters": {
                    "source": "condition:image_vehicle_detect",
                    "state": "collision",
                },
            }],
        }],
        "final_decision": {
            "name": "事故检测",
            "source_refs": ["branch:accident"],
        },
        "results": [{
            "key": "boxes",
            "name": "事故框",
            "source_ref": "branch:accident",
            "result_kind": "entities",
        }],
    }

    converted = apply_business_rule_draft(
        document,
        draft,
        build_business_capability_registry(registry),
        requested_accept=["image"],
    )
    condition = converted.skill_template.business_branches[0].condition_root
    assert condition.capability_id == "target.detect"
    assert condition.parameters["targets"][0]["phrases"] == ["vehicle collision"]
    assert EditorService(registry).apply(converted).validation_report["can_run"] is True
