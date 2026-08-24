from __future__ import annotations

import pytest

from core.business_capabilities import build_business_capability_registry
from core.business_result_projector import build_runtime_contract
from core.business_rule_draft import (
    BusinessDraftError,
    NaturalLanguageBusinessDraft,
    apply_business_rule_draft,
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
