from __future__ import annotations

import json
from types import SimpleNamespace

from core.registry import build_default_registry


class FakeCompletions:
    def __init__(self, contents):
        self.contents = list(contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, contents):
        self.chat = SimpleNamespace(completions=FakeCompletions(contents))


def test_business_region_repairs_an_open_scene_position_constraint():
    from clients.v2_planner import DeepSeekSemanticPlanner

    ledger = {
        "constraints": [{
            "kind": "position",
            "value": "on road",
            "source": "检测道路上的障碍物",
            "source_span": "道路上",
        }],
        "unresolved": [{
            "source_span": "道路上",
            "reason": "unknown position: on road",
        }],
    }
    business_rule = {
        "resources": [{
            "key": "road",
            "resource_type": "region",
            "semantic_role": "road_surface",
            "minimum_items": 1,
        }]
    }

    repaired = DeepSeekSemanticPlanner._repair_business_region_positions(
        ledger, business_rule
    )

    assert repaired["constraints"][0]["kind"] == "region_requirement"
    assert repaired["constraints"][0]["value"]["semantic_role"] == "road_surface"
    assert repaired["unresolved"] == []


def test_open_scene_position_synthesizes_missing_business_region_resource():
    from clients.v2_planner import DeepSeekSemanticPlanner

    ledger = {
        "constraints": [{
            "kind": "position",
            "value": "on road",
            "source": "检测道路上的障碍物",
            "source_span": "道路上",
        }],
        "unresolved": [],
    }
    business_rule = {
        "branches": [{
            "media_type": "image",
            "conditions": [{
                "capability_id": "spatial.membership",
                "parameters": {"scope": "full_frame"},
            }],
        }],
        "resources": [],
    }

    repaired = DeepSeekSemanticPlanner._repair_business_region_positions(
        ledger, business_rule
    )

    assert repaired["constraints"][0]["kind"] == "region_requirement"
    assert business_rule["resources"][0]["semantic_role"] == "on_road"
    condition = business_rule["branches"][0]["conditions"][0]
    assert condition["parameters"]["scope"] == "resource:on_road"


def test_manual_direction_synthesizes_resource_and_repairs_direction_parameters():
    from clients.v2_planner import DeepSeekSemanticPlanner

    ledger = {
        "constraints": [{
            "kind": "direction_relation",
            "value": {
                "relation": "opposite",
                "reference_scope": "manual",
                "reference_source": "manual",
            },
        }],
    }
    business_rule = {
        "branches": [{
            "media_type": "video",
            "conditions": [{
                "capability_id": "motion.direction",
                "parameters": {
                    "reference": "manual",
                    "minimum_reverse_angle": None,
                },
            }],
        }],
        "resources": [],
    }

    DeepSeekSemanticPlanner._repair_business_manual_directions(
        ledger, business_rule
    )

    resource = business_rule["resources"][0]
    assert resource["resource_type"] == "direction"
    parameters = business_rule["branches"][0]["conditions"][0]["parameters"]
    assert parameters["reference"] == "resource:reference_direction"
    assert parameters["relation"] == "opposite"
    assert "minimum_reverse_angle" not in parameters


def test_per_region_direction_synthesizes_region_semantics_and_drops_resource_branch():
    from clients.v2_planner import DeepSeekSemanticPlanner

    ledger = {
        "constraints": [{
            "kind": "direction_relation",
            "value": {
                "relation": "opposite",
                "reference_scope": "per_named_region",
                "reference_source": "manual",
            },
            "source": "按每个区域标注方向",
            "source_span": "按每个区域标注方向",
        }],
    }
    business_rule = {
        "branches": [
            {
                "key": "direction_setup",
                "media_type": "video",
                "conditions": [{
                    "capability_id": "motion.direction",
                    "parameters": {"source": "full_frame", "reference": "manual"},
                }],
            },
            {
                "key": "detection",
                "media_type": "video",
                "conditions": [{
                    "capability_id": "motion.wrong_way",
                    "parameters": {"reference": "manual"},
                }],
            },
        ],
        "resources": [{
            "key": "areas",
            "name": "检测区域",
            "resource_type": "region",
            "semantic_role": "area",
            "media_types": ["video"],
        }],
    }

    DeepSeekSemanticPlanner._repair_business_manual_directions(
        ledger, business_rule
    )

    region = ledger["constraints"][0]
    assert region["kind"] == "region_requirement"
    assert region["value"]["cardinality"] == "many"
    assert [item["key"] for item in business_rule["branches"]] == ["detection"]
    direction = next(
        item for item in business_rule["resources"]
        if item["resource_type"] == "direction"
    )
    assert direction["paired_region_key"] == "areas"
    parameters = business_rule["branches"][0]["conditions"][0]["parameters"]
    assert parameters["reference"] == "resource:reference_direction"


def _red_gray_ledger(top="上衣", pants="裤子"):
    return {
        "mode": "entity_query",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [
            {
                "kind": "color",
                "value": "红色",
                "source": f"检测穿红色{top}",
                "source_span": f"红色{top}",
                "carrier": top,
                "carrier_span": top,
            },
            {
                "kind": "color",
                "value": "灰色",
                "source": f"灰色{pants}的人",
                "source_span": f"灰色{pants}",
                "carrier": pants,
                "carrier_span": pants,
            },
        ],
        "logic": "all",
        "unresolved": [],
    }


def test_v2_planner_extracts_semantics_then_uses_deterministic_compiler():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测穿红色上衣、灰色裤子的人。"
    fake = FakeClient([json.dumps(_red_gray_ledger(), ensure_ascii=False)])
    planner = DeepSeekSemanticPlanner(build_default_registry(), client=fake, model="deepseek-test")

    result = planner.compile(
        instruction,
        requested_accept=["image", "video"],
        skill_id="red_top_gray_pants_person",
        display_name="红上衣灰裤人员",
    )

    assert result.package.compile_status == "compiled"
    assert result.package.input.accept == ["image", "video"]
    assert result.attempts == 1
    assert result.strategy == "semantic_ir+deterministic_workflow"
    assert result.errors == []
    call = fake.chat.completions.calls[0]
    assert call["model"] == "deepseek-test"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["reasoning_effort"] == "high"
    prompt = call["messages"][0]["content"]
    assert "只输出语义账本" in prompt
    assert "不输出工作流节点" in prompt
    assert "source_span" in prompt
    assert "execution_atom_assets_read_only" not in prompt
    assert "rex.ground@" not in prompt
    assert "执行原子资产不进入 LLM 上下文" in prompt
    assert "LLM 只编排业务能力" in prompt
    assert "Python" in prompt
    assert "可独立判定、展示、保存或计时的主体链" in prompt
    assert "和、且、同时、都表示 AND/all" in prompt
    assert "或、或者、任一表示 OR/any" in prompt
    assert "只出现一个条件时保持单条件" in prompt
    assert "明确要求‘同一张/同一个/同一人’" in prompt
    assert "命名区域边界" in prompt
    assert "为每个独立区域建立一个 branch" in prompt
    assert "不要把区域1和区域2的条件塞进同一个 branch" in prompt
    assert "full_frame 仅可作为 scope" in prompt
    assert "只是技能名称，不是事件名、告警名或框标签" in prompt
    assert "不得直接复制给 final_decision.name" in prompt
    assert "用户没有明确给出的 tuning 参数必须省略" in prompt
    assert '"id":"target.detect"' in prompt
    assert '"schema_slot":"branches[].conditions[] ATOM"' in prompt
    user_payload = json.loads(call["messages"][1]["content"])
    assert user_payload["requested_skill_display_name"] == "红上衣灰裤人员"


def test_v2_planner_validates_and_returns_optional_business_rule_draft():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测人员并输出人员框。"
    payload = {
        "mode": "direct_grounding",
        "target": {
            "concept": "person",
            "source_span": "人员",
            "phrases": ["person"],
        },
        "constraints": [],
        "logic": "all",
        "unresolved": [],
        "business_rule": {
            "schema_version": "1.0",
            "media_requirement": "image",
            "branches": [
                {
                    "key": "people",
                    "name": "人员检测",
                    "media_type": "image",
                    "conditions": [
                        {
                            "key": "detect",
                            "name": "检测人员",
                            "capability_id": "target.detect",
                            "parameters": {
                                "targets": ["person"],
                                "phrases": "person",
                                "business_label": "人员",
                            },
                        }
                    ],
                }
            ],
            "final_decision": {
                "name": "人员检测结果",
                "decision_type": "detection_summary",
                "source_refs": ["branch:people"],
            },
            "results": [
                {
                    "key": "people_boxes",
                    "name": "人员框",
                    "source_ref": "condition:people.detect",
                    "result_kind": "entities",
                },
                {
                    "key": "decision",
                    "name": "人员检测结果",
                    "source_ref": "final:primary",
                    "result_kind": "decision",
                },
            ],
        },
    }
    fake = FakeClient([json.dumps(payload, ensure_ascii=False)])
    planner = DeepSeekSemanticPlanner(
        build_default_registry(), client=fake, model="deepseek-test"
    )

    result = planner.compile(
        instruction,
        requested_accept=["image"],
        skill_id="people_business_draft",
        display_name="人员业务草稿",
    )

    assert result.business_draft is not None
    assert result.business_draft["branches"][0]["key"] == "people"
    assert result.business_draft["results"][0]["result_kind"] == "entities"

    without_business = {
        key: value for key, value in payload.items() if key != "business_rule"
    }
    retry_fake = FakeClient([
        json.dumps(without_business, ensure_ascii=False),
        json.dumps(payload, ensure_ascii=False),
    ])
    required_planner = DeepSeekSemanticPlanner(
        build_default_registry(), client=retry_fake, model="deepseek-test"
    )
    required_result = required_planner.compile(
        instruction,
        requested_accept=["image"],
        skill_id="required_business_draft",
        display_name="必须生成业务草稿",
        require_business_draft=True,
    )
    assert required_result.attempts == 2
    assert required_result.business_draft is not None
    assert "缺少必需的顶层 business_rule" in required_result.errors[0]


def test_ground_surface_position_becomes_a_visible_target_phrase_not_a_region():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测地面是否有垃圾。"
    payload = {
        "mode": "direct_grounding",
        "target": {
            "concept": "litter",
            "source_span": "垃圾",
            "phrases": ["litter"],
        },
        "constraints": [{
            "kind": "position",
            "value": "on ground",
            "source": instruction,
            "source_span": "地面",
            "phrases": ["litter on ground"],
        }],
        "logic": "all",
        "unresolved": [],
        "business_rule": {
            "schema_version": "1.0",
            "media_requirement": "image",
            "branches": [{
                "key": "ground_litter",
                "name": "地面垃圾检测",
                "media_type": "image",
                "conditions": [
                    {
                        "key": "detect_litter",
                        "name": "检测垃圾",
                        "capability_id": "target.detect",
                        "parameters": {
                            "targets": ["litter"],
                            "phrases": ["litter"],
                            "business_label": "垃圾",
                        },
                    },
                    {
                        "key": "litter_on_ground",
                        "name": "垃圾在地面",
                        "capability_id": "spatial.membership",
                        "parameters": {
                            "source": "condition:detect_litter",
                            "scope": "full_frame",
                            "membership": "overlap",
                            "inside": "ground",
                        },
                    },
                ],
            }],
            "final_decision": {
                "name": "地面垃圾检测结果",
                "decision_type": "detection_summary",
                "source_refs": ["branch:ground_litter"],
            },
            "results": [{
                "key": "litter_boxes",
                "name": "垃圾框",
                "source_ref": "condition:ground_litter.detect_litter",
                "result_kind": "entities",
            }],
        },
    }
    planner = DeepSeekSemanticPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(payload, ensure_ascii=False)]),
        model="deepseek-test",
    )

    result = planner.compile(
        instruction,
        requested_accept=["image"],
        skill_id="ground_litter",
        display_name="地面垃圾检测",
    )

    assert result.package is not None
    assert result.package.semantic_ir.constraints == []
    ground = next(
        node for node in result.package.variants["image"].nodes
        if node.id == "candidates_raw"
    )
    assert ground.params["targets"][0]["phrases"] == ["litter on the ground"]
    conditions = result.business_draft["branches"][0]["conditions"]
    assert [item["capability_id"] for item in conditions] == ["target.detect"]
    assert conditions[0]["parameters"]["phrases"] == ["litter on the ground"]


def test_static_auto_media_retries_a_business_draft_that_only_builds_video():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测人员并输出人员框。"
    first = {
        "mode": "direct_grounding",
        "target": {
            "concept": "person",
            "source_span": "人员",
            "phrases": ["person"],
        },
        "constraints": [],
        "logic": "all",
        "unresolved": [],
        "business_rule": {
            "schema_version": "1.0",
            "media_requirement": "video",
            "branches": [
                {
                    "key": "people_video",
                    "name": "视频人员检测",
                    "media_type": "video",
                    "conditions": [
                        {
                            "key": "detect",
                            "name": "检测人员",
                            "capability_id": "target.detect",
                            "parameters": {
                                "targets": ["person"],
                                "phrases": "person",
                            },
                        }
                    ],
                }
            ],
            "final_decision": {
                "name": "人员检测",
                "source_refs": ["branch:people_video"],
            },
            "results": [
                {
                    "key": "decision",
                    "name": "人员检测",
                    "source_ref": "final:primary",
                    "result_kind": "decision",
                }
            ],
        },
    }
    repaired = {key: value for key, value in first.items() if key != "business_rule"}
    fake = FakeClient(
        [json.dumps(first, ensure_ascii=False), json.dumps(repaired, ensure_ascii=False)]
    )
    planner = DeepSeekSemanticPlanner(
        build_default_registry(), client=fake, model="deepseek-test"
    )

    result = planner.compile(
        instruction,
        requested_accept=["image", "video"],
        skill_id="auto_media_retry",
        display_name="人员检测",
    )

    assert result.attempts == 2
    assert result.package.input.accept == ["image", "video"]
    assert "媒体流程" in result.errors[0]


def test_v2_planner_accepts_optional_read_only_execution_context_without_putting_it_in_ir():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测穿红色上衣、灰色裤子的人。"
    fake = FakeClient([json.dumps(_red_gray_ledger(), ensure_ascii=False)])
    context = {
        "media_metadata": {
            "media_type": "video",
            "width": 1920,
            "height": 1080,
            "fps": 25.0,
        },
        "preprocessing": {
            "resize_mode": "identity",
            "sample_mode": "frame_step",
            "frame_step": 1,
        },
    }

    result = DeepSeekSemanticPlanner(build_default_registry(), client=fake).compile(
        instruction,
        requested_accept=["video"],
        skill_id="red_top_gray_pants_person",
        display_name="红上衣灰裤人员",
        execution_context=context,
    )

    call = fake.chat.completions.calls[0]
    user_payload = json.loads(call["messages"][1]["content"])
    assert user_payload["execution_context"] == context
    assert "只读执行上下文" in call["messages"][0]["content"]
    semantic_json = result.package.semantic_ir.model_dump(mode="json")
    assert "execution_context" not in semantic_json
    sample = next(
        node
        for node in result.package.variants["video"].nodes
        if node.op == "video.sample@1.1"
    )
    assert sample.params == {
        "mode": "fps",
        "fps": 1.0,
        "start_seconds": 0.0,
        "end_seconds": None,
        "max_frames": None,
    }


def test_v2_planner_prompt_exposes_generic_count_motion_direction_and_scene_requirements():
    from clients.v2_planner import DeepSeekSemanticPlanner

    prompt = DeepSeekSemanticPlanner(
        build_default_registry(), client=FakeClient([])
    )._system_prompt()

    for token in [
        "quantity",
        "motion",
        "direction_relation",
        "region_requirement",
        "aligned",
        "opposite",
        "whole_video_majority",
        "image_axis",
        "manual",
        "per_named_region",
        "固定区域",
        "标注区域",
    ]:
        assert token in prompt
    assert "不输出 resize" in prompt
    assert "不输出 ROI 坐标" in prompt
    assert "entity_exclusion" in prompt
    assert "开放英文可见部件" in prompt
    assert "剥离否定词后的同一正谓词" in prompt
    assert "排除分句不得遗漏" in prompt
    assert "排除独立目标类别" in prompt
    assert "不能把‘戴帽子的人/穿背心的人’误写成独立实体类别" in prompt
    assert "同一主体的完整框" in prompt
    assert "person wearing safety helmet" in prompt
    assert "主体血缘" in prompt
    assert "分支边界" in prompt
    assert "关系完整性" in prompt
    assert "输出类型" in prompt
    assert "执行隔离" in prompt
    assert "必须按视觉证据的定位难度排序" in prompt
    assert "关联物→‘主体与关联物处于某关系’→主体" in prompt
    assert "语义与规则的选择" in prompt
    assert "优先使用模型正向语义直接识别" in prompt
    assert "数量、命名区域、时序、速度、方向、精确几何、跨目标关系" in prompt
    assert "禁止把 not/without/no 发送给检测模型" in prompt
    assert "wearing、carrying、containing、loaded with、attached to、connected to" in prompt
    assert "不得把所有关系统一改写成 wearing 或 with" in prompt
    assert "attribute.color.verification_logic" in prompt
    assert "FRACTION_ONLY" in prompt
    assert "SEMANTIC_ONLY" in prompt
    assert "不得把基础目标检测误写成独立业务条件" in prompt
    assert "不得根据具体实体名、颜色名、技能名或示例名称建立特殊分支" in prompt
    assert "P01-P13 预置演示技能是回归样例而不是可复制的工作流模板" in prompt
    assert "business_capability_assets" in prompt
    assert "execution_atom_assets_read_only" not in prompt
    assert "rex.ground@" not in prompt
    assert '"schema_slot":"branches[].time"' in prompt
    assert '"schema_slot":"patterns[]"' in prompt
    assert '"schema_slot":"results[]"' in prompt
    assert "系统基础原子按媒体、资源、证据和输出闭包自动补齐" in prompt


def test_v2_planner_repairs_fixed_region_count_when_model_omits_grouping():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测固定区域内有大于2辆车辆，触发事件告警"
    ledger = {
        "mode": "workflow",
        "target": {"concept": "vehicle", "source_span": "车辆", "phrases": ["vehicle"]},
        "constraints": [{
            "kind": "quantity",
            "value": {"measure": "count", "operator": ">", "value": 2},
            "source": instruction,
            "source_span": "大于2辆车辆",
        }],
        "logic": "all",
        "unresolved": [],
    }
    planner = DeepSeekSemanticPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(ledger, ensure_ascii=False)]),
        model="deepseek-test",
    )

    result = planner.compile(
        instruction,
        requested_accept=["video"],
        skill_id="fixed_region_count",
        display_name="我的视觉技能",
    )

    assert result.errors == []
    variant = result.package.variants["video"]
    assert any(node.op == "measure.region_count@1.0" for node in variant.nodes)
    assert any(slot.kind == "region" for slot in variant.configuration_slots)


def test_v2_planner_turns_missing_count_threshold_into_step_03_pending_decision():
    from clients.v2_planner import DeepSeekSemanticPlanner
    from core.editor_generation import build_editor_document, resolve_pending_decision

    instruction = "区域1有穿红色衣服、灰色裤子的人，并且区域2人的数量大于等于，则发出事件告警"
    ledger = _red_gray_ledger("衣服", "裤子")
    for constraint in ledger["constraints"]:
        constraint["source"] = instruction
    ledger["unresolved"] = [
        {
            "source_span": "数量大于等于",
            "reason": "数量比较阈值缺失",
        },
        {
            "source_span": "发出事件告警",
            "reason": "告警输出不是视觉条件",
        },
    ]
    planner = DeepSeekSemanticPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(ledger, ensure_ascii=False)]),
        model="deepseek-test",
    )

    result = planner.compile(
        instruction,
        requested_accept=["image", "video"],
        skill_id="multi_region_people_alert",
        display_name="多区域人员告警",
    )

    assert result.package is not None
    quantity = next(
        item for item in result.package.semantic_ir.constraints
        if item.kind == "quantity"
    )
    assert quantity.value == {"measure": "count", "operator": ">=", "value": 1}
    document = build_editor_document(result.package, source_type="natural_language")
    decision = next(
        item for item in document.skill_template.pending_decisions
        if item.decision_id == "count_threshold"
    )
    assert decision.resolution.blocks("run")
    assert decision.affected_ids

    resolved = resolve_pending_decision(document, "count_threshold", 3)
    assert any(
        item.target_id in decision.affected_ids
        and item.parameter == "value"
        and item.value == 3
        for item in resolved.user_overrides
    )


def test_v2_planner_reports_empty_ledger_without_json_parser_noise():
    from clients.v2_planner import DeepSeekSemanticPlanner

    result = DeepSeekSemanticPlanner(
        build_default_registry(), client=FakeClient(["", ""])
    ).compile(
        "检测人员",
        requested_accept=["image"],
        skill_id="people",
        display_name="人员",
    )

    assert result.package is None
    assert result.errors == [
        "LLM returned an empty semantic ledger",
        "LLM returned an empty semantic ledger",
    ]


def test_v2_planner_retries_empty_thinking_response_without_thinking():
    from clients.v2_planner import DeepSeekSemanticPlanner

    fake = FakeClient(["", json.dumps(_red_gray_ledger(), ensure_ascii=False)])
    result = DeepSeekSemanticPlanner(
        build_default_registry(), client=fake
    ).compile(
        "检测穿红色上衣、灰色裤子的人。",
        requested_accept=["image"],
        skill_id="red_gray_person",
        display_name="红衣灰裤人员",
    )

    assert result.package is not None
    assert result.attempts == 2
    assert fake.chat.completions.calls[0]["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert fake.chat.completions.calls[1]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert fake.chat.completions.calls[1]["temperature"] == 0.0
    assert not any(
        message["role"] == "assistant" and not message["content"]
        for message in fake.chat.completions.calls[1]["messages"]
    )


def test_v2_planner_repairs_nonempty_second_ledger_after_initial_empty_response():
    from clients.v2_planner import DeepSeekSemanticPlanner

    invalid = _red_gray_ledger()
    invalid["constraints"][0]["source_span"] = "蓝色上衣"
    fake = FakeClient([
        "",
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(_red_gray_ledger(), ensure_ascii=False),
    ])
    result = DeepSeekSemanticPlanner(
        build_default_registry(), client=fake
    ).compile(
        "检测穿红色上衣、灰色裤子的人。",
        requested_accept=["image"],
        skill_id="red_gray_person",
        display_name="红衣灰裤人员",
    )

    assert result.package is not None
    assert result.attempts == 3
    assert all(
        call["extra_body"] == {"thinking": {"type": "disabled"}}
        for call in fake.chat.completions.calls[1:]
    )


def test_v2_planner_treats_manual_region_geometry_as_step_03_configuration():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测区域1内的人"
    ledger = {
        "mode": "workflow",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [
            {
                "kind": "region_requirement",
                "value": {
                    "source": "manual", "cardinality": "one",
                    "semantic_role": "region_1",
                    "allowed_shapes": ["rectangle", "polygon"],
                },
                "source": "区域1",
                "source_span": "区域1",
            },
            {
                "kind": "spatial_relation",
                "value": {
                    "relation": "inside_roi",
                    "region": {
                        "source": "manual",
                        "semantic_role": "region_1",
                        "shape": "polygon",
                        "allowed_shapes": ["rectangle", "polygon"],
                    },
                },
                "source": "区域1内",
                "source_span": "区域1内",
            },
        ],
        "logic": "all",
        "unresolved": [{
            "source_span": "区域1",
            "reason": "区域几何范围需要用户标注",
        }],
    }
    result = DeepSeekSemanticPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(ledger, ensure_ascii=False)]),
    ).compile(
        instruction,
        requested_accept=["video"],
        skill_id="region_people",
        display_name="区域人员",
    )

    assert result.package is not None
    assert result.package.semantic_ir.unresolved == []
    assert result.package.variants["video"].configuration_slots


def test_v2_planner_repairs_invalid_source_span_once():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测穿红色上衣、灰色裤子的人。"
    invalid = _red_gray_ledger()
    invalid["constraints"][0]["source_span"] = "蓝色上衣"
    fake = FakeClient([
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(_red_gray_ledger(), ensure_ascii=False),
    ])

    result = DeepSeekSemanticPlanner(build_default_registry(), client=fake).compile(
        instruction,
        requested_accept=["image"],
        skill_id="red_top_gray_pants_person",
        display_name="红上衣灰裤人员",
    )

    assert result.attempts == 2
    assert result.package.compile_status == "compiled"
    assert "source_span is not present" in result.errors[0]
    assert "上一次语义账本无效" in fake.chat.completions.calls[1]["messages"][-1]["content"]


def test_v2_planner_repairs_missing_target_fields_deterministically():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测穿红色上衣、灰色裤子的人。"
    ledger = _red_gray_ledger()
    ledger["target"] = {
        "concept": "",
        "source_span": "不存在的目标片段",
        "phrases": [],
    }
    fake = FakeClient([json.dumps(ledger, ensure_ascii=False)])

    result = DeepSeekSemanticPlanner(build_default_registry(), client=fake).compile(
        instruction,
        requested_accept=["image"],
        skill_id="multi_region_people",
        display_name="多区域人员告警",
    )

    assert result.package is not None
    assert result.attempts == 1
    assert result.package.semantic_ir.target.concept == "person"
    assert result.package.semantic_ir.target.source_span == "人"
    assert result.package.semantic_ir.target.phrases == ["person"]


def test_v2_planner_uses_third_attempt_for_repeated_semantic_ledger_failures():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "区域1有穿红色衣服、灰色裤子的人，区域2有至少2个人，则发出告警。"
    ledgers = [_red_gray_ledger("衣服", "裤子") for _ in range(3)]
    for ledger in ledgers:
        ledger["constraints"][0]["source"] = "区域1有穿红色衣服、灰色裤子的人"
        ledger["constraints"][1]["source"] = "区域1有穿红色衣服、灰色裤子的人"
    first, second, valid = ledgers
    first["constraints"][0]["source_span"] = "蓝色衣服"
    second["constraints"][1]["source_span"] = "绿色裤子"

    result = DeepSeekSemanticPlanner(
        build_default_registry(),
        client=FakeClient([
            json.dumps(first, ensure_ascii=False),
            json.dumps(second, ensure_ascii=False),
            json.dumps(valid, ensure_ascii=False),
        ]),
    ).compile(
        instruction,
        requested_accept=["image"],
        skill_id="multi_region_people",
        display_name="多区域人员告警",
    )

    assert result.package is not None
    assert result.attempts == 3


def test_v2_planner_returns_needs_review_without_direct_grounding_on_repeated_failure():
    from clients.v2_planner import DeepSeekSemanticPlanner

    instruction = "检测可能存在高空坠落风险的人员"
    fake = FakeClient(["not json", "still not json"])

    result = DeepSeekSemanticPlanner(build_default_registry(), client=fake).compile(
        instruction,
        requested_accept=["image", "video"],
        skill_id="fall_risk_person",
        display_name="高空坠落风险人员",
    )

    assert result.package is None
    assert result.attempts == 2
    assert result.strategy == "needs_review"
    assert result.degraded is False
    assert len(result.errors) == 2
    assert all("Expecting value" not in item for item in result.errors)
    assert all("无法读取" in item for item in result.errors)


def test_v2_planner_accepts_json_fence_without_exposing_parser_details():
    from clients.v2_planner import DeepSeekSemanticPlanner

    fenced = "```json\n" + json.dumps(_red_gray_ledger(), ensure_ascii=False) + "\n```"
    result = DeepSeekSemanticPlanner(
        build_default_registry(), client=FakeClient([fenced])
    ).compile(
        "检测穿红色上衣、灰色裤子的人。",
        requested_accept=["image"],
        skill_id="fenced_business_rule",
        display_name="围栏JSON兼容",
    )

    assert result.package is not None
    assert result.attempts == 1


def test_v2_planner_paraphrases_share_semantic_hash_and_workflow_topology():
    from clients.v2_planner import DeepSeekSemanticPlanner

    cases = [
        ("检测穿红色上衣、灰色裤子的人。", _red_gray_ledger("上衣", "裤子")),
        ("识别穿红色上衣、灰色长裤的人。", _red_gray_ledger("上衣", "长裤")),
    ]
    results = []
    for instruction, ledger in cases:
        ledger["constraints"][0]["source"] = instruction.split("、")[0]
        ledger["constraints"][1]["source"] = instruction.split("、")[1].rstrip("。")
        fake = FakeClient([json.dumps(ledger, ensure_ascii=False)])
        results.append(
            DeepSeekSemanticPlanner(build_default_registry(), client=fake).compile(
                instruction,
                requested_accept=["image"],
                skill_id="red_top_gray_pants_person",
                display_name="红上衣灰裤人员",
            ).package
        )

    assert results[0].semantic_ir.semantic_hash == results[1].semantic_ir.semantic_hash
    assert [node.op for node in results[0].variants["image"].nodes] == [
        node.op for node in results[1].variants["image"].nodes
    ]
    def semantic_params(package):
        return [
            (
                {key: value for key, value in node.params.items() if key != "label"}
                if node.op == "objects.relabel@1.0"
                else node.params
            )
            for node in package.variants["image"].nodes
        ]

    # The executable semantics are paraphrase-stable.  The final evidence
    # label deliberately preserves each user's own complete predicate.
    assert semantic_params(results[0]) == semantic_params(results[1])
    labels = [
        next(
            node.params["label"]
            for node in package.variants["image"].nodes
            if node.op == "objects.relabel@1.0"
        )
        for package in results
    ]
    assert labels == ["穿红色上衣、灰色裤子的人", "穿红色上衣、灰色长裤的人"]
