import json
from types import SimpleNamespace

from PIL import Image

from core.registry import build_default_registry
from core.validator import validate_skill


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


def test_rex_parser_clamps_tokens_and_gateway_returns_normalized_boxes():
    from clients.rex_client import RexGateway, parse_detection_tokens

    raw = (
        "<|object_ref_start|>person<|object_ref_end|>"
        "<|box_start|><100><200><500><800>,<0><0><1200><999><|box_end|>"
    )
    parsed = parse_detection_tokens(raw)
    assert parsed == [
        {"phrase": "person", "bbox": [100 / 999, 200 / 999, 500 / 999, 800 / 999]},
        {"phrase": "person", "bbox": [0.0, 0.0, 1.0, 1.0]},
    ]

    fake = FakeClient([raw])
    gateway = RexGateway(client=fake, model="rex-test")
    detections = gateway.detect(Image.new("RGB", (20, 10), "white"), ["person"])
    assert detections[0]["phrase"] == "person"
    assert detections[0]["raw_output"] == raw
    call = fake.chat.completions.calls[0]
    assert call["model"] == "rex-test"
    assert call["messages"][1]["content"][0]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )
    assert "Detect person" in call["messages"][1]["content"][1]["text"]
    assert call["extra_body"]["skip_special_tokens"] is False


def test_rex_gateway_uses_query_prompt_but_keeps_fixed_box_contract():
    from clients.rex_client import RexGateway

    raw = (
        "<|object_ref_start|>person<|object_ref_end|>"
        "<|box_start|><100><200><500><800><|box_end|>"
    )
    fake = FakeClient([raw])

    RexGateway(client=fake).detect(
        Image.new("RGB", (20, 10), "white"),
        ["person"],
        query_prompt="Someone fell down",
    )

    prompt = fake.chat.completions.calls[0]["messages"][1]["content"][1]["text"]
    assert prompt.startswith("Someone fell down.")
    assert "Return every visible instance" in prompt
    assert "bounding box coordinates" in prompt


def test_rex_parser_normalizes_reversed_box_corners():
    from clients.rex_client import parse_detection_tokens

    raw = (
        "<|object_ref_start|>vehicle<|object_ref_end|>"
        "<|box_start|><800><700><100><200><|box_end|>"
    )

    assert parse_detection_tokens(raw) == [{
        "phrase": "vehicle",
        "bbox": [100 / 999, 200 / 999, 800 / 999, 700 / 999],
    }]


def valid_image_spec():
    return {
        "version": "0.1",
        "name": "person_detector",
        "display_name": "人员检测",
        "original_instruction": "检测人员",
        "compile_status": "compiled",
        "input": {"accept": ["image"]},
        "nodes": [
            {"id": "image", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}},
            {"id": "resize", "op": "image.resize@1.0", "inputs": {"frames": "$image"}, "params": {"long_side": 1280}},
            {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": "$resize"}, "params": {"targets": [{"label": "人员", "phrases": ["person"]}]}},
            {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": "$image", "objects": "$objects"}, "params": {}},
        ],
        "outputs": {"media": "$draw"},
    }


def legacy_deepseek_planner_uses_registry_json_mode_and_one_repair():
    from clients.planner_client import DeepSeekPlanner

    fake = FakeClient(["not json", json.dumps(valid_image_spec(), ensure_ascii=False)])
    registry = build_default_registry()
    planner = DeepSeekPlanner(registry, client=fake, model="deepseek-test")

    result = planner.compile("检测人员", "image")

    assert result.spec.name == "person_detector"
    assert result.attempts == 1
    assert result.degraded is False
    assert validate_skill(result.spec, registry) == []
    calls = fake.chat.completions.calls
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert calls[0]["extra_body"] == {"thinking": {"type": "enabled"}}
    assert calls[0]["reasoning_effort"] == "high"
    assert "temperature" not in calls[0]
    assert calls[0]["max_tokens"] == 8192
    assert calls[0]["model"] == "deepseek-test"
    assert "rex.ground@1.0" in calls[0]["messages"][0]["content"]
    assert '"accept"' in calls[0]["messages"][0]["content"]
    assert '"params"' in calls[0]["messages"][0]["content"]
    assert "上一次输出无效" in calls[1]["messages"][-1]["content"]


def test_deepseek_planner_degrades_to_executable_direct_grounding():
    from clients.planner_client import DeepSeekPlanner

    fake = FakeClient(["bad", "still bad"])
    registry = build_default_registry()
    result = DeepSeekPlanner(registry, client=fake).compile(
        "检测所有疑似危险目标", "video"
    )

    assert result.degraded is True
    assert result.attempts == 2
    assert result.spec.compile_status == "degraded"
    assert result.spec.input.accept == ["video"]
    assert validate_skill(result.spec, registry) == []
    assert [node.op for node in result.spec.nodes] == [
        "media.video@1.0",
        "video.sample@1.0",
        "image.resize@1.0",
        "rex.ground@1.0",
        "output.draw@1.0",
    ]


def test_planner_thinking_mode_can_be_disabled_explicitly():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "人员",
        "entity": {"zh": "人员", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["检测人员"], "source_span": "人员",
            "kind": "visual_attribute", "dimension": "appearance", "value": "visible",
            "phrases": ["visible person"], "region": "whole",
        }], "absent": [],
    }
    fake = FakeClient([json.dumps(intent, ensure_ascii=False)])
    planner = DeepSeekPlanner(
        build_default_registry(), client=fake, thinking=False, reasoning_effort="low"
    )
    planner.compile("检测人员", "image")
    call = fake.chat.completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in call
    assert call["temperature"] == 0.0


def legacy_deepseek_planner_uses_fixed_no_helmet_policy_without_calling_llm():
    from clients.planner_client import DeepSeekPlanner

    fake = FakeClient([])
    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "检测没有戴安全帽的施工人员", "image"
    )
    association = next(node for node in result.spec.nodes if node.id == "has_helmet")
    assert fake.chat.completions.calls == []
    assert result.attempts == 0
    assert result.strategy == "fixed_policy:no_helmet"
    assert result.degraded is False
    assert association.params == {
        "relation": "center_in_subject_region",
        "threshold": 0.0,
        "subject_region": [0.0, 0.0, 1.0, 0.35],
    }


def legacy_deepseek_planner_fixed_no_helmet_policy_remains_structured():
    from clients.planner_client import DeepSeekPlanner

    result = DeepSeekPlanner(build_default_registry(), client=FakeClient([])).compile(
        "检测没有戴安全帽的施工人员", "image"
    )
    assert result.degraded is False
    assert result.attempts == 0
    assert result.strategy == "fixed_policy:no_helmet"
    assert [node.op for node in result.spec.nodes] == [
        "media.image@1.0",
        "rex.ground@1.0",
        "rex.ground@1.0",
        "spatial.associate@1.0",
        "logic.not@1.0",
        "filter.apply@1.0",
        "output.draw@1.0",
    ]


def legacy_deepseek_planner_compiles_vehicle_exclusions_as_explicit_filter_graph():
    from clients.planner_client import DeepSeekPlanner

    fake = FakeClient([])
    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "检测轿车、客车、人，排除货车、面包车。", "image"
    )

    assert fake.chat.completions.calls == []
    assert result.attempts == 0
    assert result.degraded is False
    assert result.strategy == "fixed_policy:vehicle_exclusion"
    assert [node.op for node in result.spec.nodes] == [
        "media.image@1.0",
        "rex.ground@1.0",
        "rex.ground@1.0",
        "spatial.associate@1.0",
        "logic.not@1.0",
        "filter.apply@1.0",
        "output.draw@1.0",
    ]
    included = next(node for node in result.spec.nodes if node.id == "included")
    excluded = next(node for node in result.spec.nodes if node.id == "excluded")
    assert included.params["targets"] == [
        {"label": "客车", "phrases": ["coach bus"]},
        {"label": "轿车", "phrases": ["passenger car"]},
        {"label": "人", "phrases": ["person"]},
    ]
    assert excluded.params["targets"] == [
        {"label": "货车", "phrases": ["cargo truck"]},
        {"label": "面包车", "phrases": ["panel van"]},
    ]
    assert result.spec.outputs["objects"] == "$filtered"
    draw = next(node for node in result.spec.nodes if node.id == "draw")
    assert draw.inputs["objects"] == "$filtered"


def legacy_deepseek_planner_expands_reflective_vest_worker_prompt_for_crouching_pose():
    from clients.planner_client import DeepSeekPlanner

    fake = FakeClient([])
    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "检测穿着反光背心的工作人员", "image"
    )

    assert fake.chat.completions.calls == []
    assert result.attempts == 0
    assert result.degraded is False
    assert result.strategy == "fixed_policy:reflective_vest_pose"
    ground = next(node for node in result.spec.nodes if node.op == "rex.ground@1.0")
    assert ground.params["targets"] == [{
        "label": "穿着反光背心的工作人员",
        "phrases": [
            "worker wearing reflective vest",
            "crouching worker wearing reflective vest",
        ],
    }]
    assert ground.params["deduplicate_metric"] == "ios"
    assert ground.params["deduplicate_iou"] == 0.7


def legacy_deepseek_planner_compiles_generic_entity_exclusion_intent_to_fixed_filter_graph():
    from clients.planner_client import DeepSeekPlanner

    intent = json.dumps({
        "mode": "entity_contrast",
        "target_label": "蹲下的人",
        "positive_phrase": "person squatting with both knees bent",
        "exclude_label": "正坐着的人",
        "exclude_phrase": "person sitting with support under the buttocks",
        "reason": "蹲姿与坐姿由臀部是否获得物体支撑区分。",
    }, ensure_ascii=False)
    fake = FakeClient([intent])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "检测图像中的在蹲下的人，姿态为双膝弯曲，排除正坐着的人", "image"
    )

    assert result.strategy == "llm_intent:entity_contrast"
    assert result.attempts == 1
    assert result.degraded is False
    assert [node.op for node in result.spec.nodes] == [
        "media.image@1.0",
        "rex.ground@1.0",
        "rex.ground@1.0",
        "spatial.associate@1.0",
        "logic.not@1.0",
        "filter.apply@1.0",
        "output.draw@1.0",
    ]
    positive = next(node for node in result.spec.nodes if node.id == "positive")
    excluded = next(node for node in result.spec.nodes if node.id == "excluded")
    assert positive.params["targets"] == [{
        "label": "蹲下的人", "phrases": ["person squatting with both knees bent"]
    }]
    assert excluded.params["targets"] == [{
        "label": "正坐着的人", "phrases": ["person sitting with support under the buttocks"]
    }]
    assert result.spec.outputs["objects"] == "$filtered"


def legacy_deepseek_planner_compiles_generic_entity_query_constraints_without_task_policy():
    from clients.planner_client import DeepSeekPlanner

    intents = [
        {
            "mode": "entity_query",
            "label": "穿反光衣的人",
            "candidate_phrases": [
                "person wearing reflective vest",
                "crouching person wearing reflective vest",
            ],
            "constraints": [],
        },
        {
            "mode": "entity_query",
            "label": "穿白衣的人",
            "candidate_phrases": ["person"],
            "constraints": [{
                "kind": "color_fraction",
                "color": "white",
                "subject_region": [0.0, 0.15, 1.0, 0.7],
                "min_fraction": 0.2,
            }],
        },
        {
            "mode": "entity_query",
            "label": "蹲着的人",
            "candidate_phrases": ["person squatting with both knees bent"],
            "constraints": [{
                "kind": "exclude_overlap",
                "label": "有支撑的坐姿人员",
                "phrases": ["person sitting with support under buttocks"],
                "threshold": 0.5,
            }],
        },
    ]
    instructions = [
        "识别穿反光衣的人",
        "识别穿白衣的人",
        "识别蹲着的人，双膝弯曲、臀部无支撑",
    ]

    for intent, instruction in zip(intents, instructions):
        fake = FakeClient([json.dumps(intent, ensure_ascii=False)])
        result = DeepSeekPlanner(build_default_registry(), client=fake).compile(instruction, "image")
        assert result.strategy == "llm_intent:entity_query"
        assert len(fake.chat.completions.calls) == 1
        expected_objects = "$filtered" if intent["constraints"] else "$candidates"
        assert result.spec.outputs["objects"] == expected_objects

    white_result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(intents[1], ensure_ascii=False)])
    ).compile(instructions[1], "image")
    assert "visual.color_fraction@1.0" in [node.op for node in white_result.spec.nodes]

    squat_result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(intents[2], ensure_ascii=False)])
    ).compile(instructions[2], "image")
    assert [node.op for node in squat_result.spec.nodes][-5:] == [
        "rex.ground@1.0",
        "spatial.associate@1.0",
        "logic.not@1.0",
        "filter.apply@1.0",
        "output.draw@1.0",
    ]


def test_deepseek_planner_compiles_atomic_constraint_ledger_without_task_branches():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query",
        "label": "蹲着的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别蹲着的人", "双膝弯曲"],
            "kind": "pose",
            "phrases": ["person squatting with both knees bent"],
            "region": "whole",
        }],
        "absent": [{
            "sources": ["臀部无支撑"],
            "kind": "pose",
            "phrases": ["person sitting with support under buttocks"],
            "region": "lower_body",
        }],
    }
    fake = FakeClient([json.dumps(intent, ensure_ascii=False)])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "识别蹲着的人，双膝弯曲、臀部无支撑", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert len(fake.chat.completions.calls) == 1
    assert [node.op for node in result.spec.nodes] == [
        "media.image@1.0",
        "rex.ground@1.0",
        "image.tile@1.0",
        "rex.ground@1.0",
        "spatial.associate@1.0",
        "filter.apply@1.0",
        "rex.ground@1.0",
        "spatial.associate@1.0",
        "logic.not@1.0",
        "filter.apply@1.0",
        "output.draw@1.0",
    ]
    assert result.spec.outputs["objects"] == "$filtered"


def test_entity_intent_repairs_misplaced_negative_constraint_instead_of_free_workflow_fallback():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "蹲着的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别蹲着的人", "双膝弯曲", "臀部无支撑"],
            "kind": "pose",
            "phrases": ["person crouching with bent knees and unsupported hips"],
            "region": "whole",
        }],
        "absent": [],
    }
    repaired = {
        "mode": "entity_query",
        "label": "蹲着的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别蹲着的人", "双膝弯曲"],
            "kind": "pose",
            "phrases": ["person squatting with both knees bent"],
            "region": "whole",
        }],
        "absent": [{
            "sources": ["臀部无支撑"],
            "kind": "pose",
            "phrases": ["person sitting with support under buttocks"],
            "region": "lower_body",
        }],
    }
    fake = FakeClient([
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(repaired, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "识别蹲着的人，双膝弯曲、臀部无支撑", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2
    assert len(fake.chat.completions.calls) == 2
    assert "unsupported" in result.raw_outputs[0]
    assert result.spec.outputs["objects"] == "$filtered"


def test_wearable_predicate_uses_generic_multiscale_evidence_without_pose_alias():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query",
        "label": "穿可见装备的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["穿可见装备"],
            "kind": "wearable",
            "phrases": ["wearing visible equipment"],
            "region": "upper_body",
        }],
        "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("穿可见装备", "image")

    predicate = next(node for node in result.spec.nodes if node.id == "constraint_1_objects")
    assert predicate.params["targets"][0]["phrases"] == [
        "person wearing visible equipment",
    ]
    evidence = next(node for node in result.spec.nodes if node.id == "evidence_frames")
    assert evidence.op == "image.tile@1.0"
    assert evidence.params["include_full_frame"] is True
    assert predicate.inputs["frames"] == "$evidence_frames"


def test_pose_predicate_repairs_incomplete_fragment_to_independently_detectable_phrase():
    from clients.planner_client import DeepSeekPlanner

    base = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["缺失某种姿态条件"],
            "kind": "pose",
            "phrases": ["buttocks supported"],
            "region": "whole",
        }],
    }
    repaired = json.loads(json.dumps(base, ensure_ascii=False))
    repaired["absent"][0]["phrases"] = ["person sitting with support under the buttocks"]
    fake = FakeClient([
        json.dumps(base, ensure_ascii=False),
        json.dumps(repaired, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "缺失某种姿态条件", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2
    excluded = next(node for node in result.spec.nodes if node.id == "constraint_1_objects")
    assert excluded.params["targets"][0]["phrases"] == [
        "person sitting with support under the buttocks"
    ]


def test_pose_predicate_requires_explicit_action_state_not_only_body_attribute():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["缺失姿态条件"],
            "kind": "pose",
            "phrases": ["person with body supported"],
            "region": "whole",
        }],
    }
    repaired = json.loads(json.dumps(invalid, ensure_ascii=False))
    repaired["absent"][0]["phrases"] = ["person sitting with body supported by an object"]

    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(repaired, ensure_ascii=False),
        ]),
    ).compile("缺失姿态条件", "image")

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2


def test_entity_intent_receives_atomic_clause_ledger_for_complete_coverage():
    from clients.planner_client import DeepSeekPlanner

    valid = {
        "mode": "entity_query",
        "label": "蹲着的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别蹲着的人", "双膝弯曲"],
            "kind": "pose",
            "phrases": ["person squatting with knees bent"],
            "region": "whole",
        }],
        "absent": [{
            "sources": ["臀部无支撑"],
            "kind": "pose",
            "phrases": ["person sitting with hips supported by an object"],
            "region": "whole",
        }],
    }
    fake = FakeClient([json.dumps(valid, ensure_ascii=False)])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "识别蹲着的人，双膝弯曲、臀部无支撑", "image"
    )

    request = json.loads(fake.chat.completions.calls[0]["messages"][1]["content"])
    assert request == {
        "instruction": "识别蹲着的人，双膝弯曲、臀部无支撑",
        "clauses": ["识别蹲着的人", "双膝弯曲", "臀部无支撑"],
    }
    assert result.strategy == "llm_intent:entity_query"


def test_supported_predicate_requires_visible_support_source():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["臀部无支撑"],
            "kind": "pose",
            "phrases": ["person sitting with buttocks supported"],
            "region": "whole",
        }],
    }
    repaired = json.loads(json.dumps(invalid, ensure_ascii=False))
    repaired["absent"][0]["phrases"] = [
        "person sitting with buttocks supported by an object"
    ]
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(repaired, ensure_ascii=False),
        ]),
    ).compile("臀部无支撑", "image")

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2


def test_invalid_entity_intent_never_falls_through_to_free_workflow_compilation():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别目标人员"],
            "kind": "pose",
            "phrases": ["person with vague body attribute"],
            "region": "whole",
        }],
        "absent": [],
    }
    fake = FakeClient([
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(invalid, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "识别目标人员", "image"
    )

    assert len(fake.chat.completions.calls) == 2
    assert result.strategy == "llm_intent:entity_query_degraded"
    assert result.degraded is True
    assert result.spec.compile_status == "degraded"


def test_entity_intent_repair_prompt_explains_generic_pose_contract():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["缺失姿态"],
            "kind": "pose",
            "phrases": ["person with body supported by an object"],
            "region": "whole",
        }],
    }
    repaired = json.loads(json.dumps(invalid, ensure_ascii=False))
    repaired["absent"][0]["phrases"] = ["person sitting with body supported by an object"]
    fake = FakeClient([
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(repaired, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "缺失姿态", "image"
    )

    repair_text = fake.chat.completions.calls[1]["messages"][-1]["content"]
    assert "明确姿态动作词" in repair_text
    assert "保持 clauses 覆盖不变" in repair_text
    assert result.strategy == "llm_intent:entity_query"


def test_absent_pose_must_use_counter_state_not_repeat_required_pose():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["目标姿态"], "kind": "pose",
            "phrases": ["person squatting with knees bent"], "region": "whole",
        }],
        "absent": [{
            "sources": ["排除有支撑"], "kind": "pose",
            "phrases": ["person squatting with hips supported by an object"], "region": "whole",
        }],
    }
    repaired = json.loads(json.dumps(invalid, ensure_ascii=False))
    repaired["absent"][0]["phrases"] = [
        "person sitting with hips supported by an object"
    ]
    fake = FakeClient([
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(repaired, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "目标姿态、排除有支撑", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2
    repair_text = fake.chat.completions.calls[1]["messages"][-1]["content"]
    assert "互斥反例状态" in repair_text


def test_support_relation_predicate_is_mechanically_rendered_from_structured_fields():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["臀部无支撑"],
            "kind": "support_relation",
            "action": "sitting",
            "subject_part": "buttocks",
            "relation": "supported_by",
            "object": "object",
            "region": "whole",
        }],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("臀部无支撑", "image")

    assert result.strategy == "llm_intent:entity_query"
    relation = next(node for node in result.spec.nodes if node.id == "constraint_1_objects")
    assert relation.params["targets"][0]["phrases"] == [
        "person sitting with buttocks supported by an object"
    ]
    assert relation.inputs["frames"] == "$media"
    assert not [node for node in result.spec.nodes if node.id == "evidence_frames"]


def test_support_relation_repairs_non_action_and_article_prefixed_object_fields():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["无支撑"], "kind": "support_relation",
            "action": "supported by", "subject_part": "body",
            "relation": "supported_by", "object": "a surface", "region": "whole",
        }],
    }
    repaired = json.loads(json.dumps(invalid, ensure_ascii=False))
    repaired["absent"][0]["action"] = "sitting"
    repaired["absent"][0]["object"] = "surface"
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(repaired, ensure_ascii=False),
        ]),
    ).compile("无支撑", "image")

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2
    node = next(node for node in result.spec.nodes if node.id == "constraint_1_objects")
    assert node.params["targets"][0]["phrases"] == [
        "person sitting with body resting on a surface"
    ]


def test_clause_polarity_is_fixed_by_language_markers_not_chosen_by_llm():
    from clients.planner_client import DeepSeekPlanner

    invalid = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["臀部无支撑"], "kind": "support_relation",
            "action": "squatting", "subject_part": "buttocks",
            "relation": "supported_by", "object": "nothing", "region": "lower_body",
        }],
        "absent": [],
    }
    repaired = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["臀部无支撑"], "kind": "support_relation",
            "action": "sitting", "subject_part": "buttocks",
            "relation": "supported_by", "object": "object", "region": "lower_body",
        }],
    }
    fake = FakeClient([
        json.dumps(invalid, ensure_ascii=False),
        json.dumps(repaired, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "臀部无支撑", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 2
    assert "固定极性" in fake.chat.completions.calls[1]["messages"][-1]["content"]


def test_compound_clause_is_split_into_wearable_and_color_atomic_constraints():
    from clients.planner_client import DeepSeekPlanner

    compressed = {
        "mode": "entity_query",
        "label": "穿着黄色反光衣的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别穿着黄色反光衣的人"],
            "kind": "wearable",
            "phrases": ["wearing yellow reflective vest"],
            "region": "upper_body",
        }],
        "absent": [],
    }
    atomic = {
        "mode": "entity_query",
        "label": "穿着黄色反光衣的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [
            {
                "sources": ["识别穿着黄色反光衣的人"],
                "kind": "wearable",
                "phrases": ["wearing reflective vest"],
                "region": "upper_body",
            },
            {
                "sources": ["识别穿着黄色反光衣的人"],
                "kind": "color",
                "phrases": ["yellow"],
                "region": "upper_body",
            },
        ],
        "absent": [],
    }
    fake = FakeClient([
        json.dumps(compressed, ensure_ascii=False),
        json.dumps(atomic, ensure_ascii=False),
    ])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "识别穿着黄色反光衣的人", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 1
    vest = next(node for node in result.spec.nodes if node.id == "constraint_1_objects")
    assert vest.params["targets"][0]["phrases"] == ["person wearing reflective vest"]
    color = next(node for node in result.spec.nodes if node.id == "constraint_2_color")
    assert color.params["color"] == "yellow"
    assert color.params["min_fraction"] == 0.1
    assert result.spec.outputs["objects"] == "$filtered"


def test_compiler_normalizes_color_only_clothing_without_task_specific_retry():
    from clients.planner_client import DeepSeekPlanner

    compressed = {
        "mode": "entity_query", "label": "穿白衣的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别穿白衣的人"], "source_span": "穿白衣",
            "kind": "visual_attribute", "dimension": "wearable",
            "value": "white clothing", "phrases": ["wearing white clothing"],
            "region": "upper_body",
        }], "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(compressed, ensure_ascii=False)])
    ).compile("识别穿白衣的人", "image")
    assert result.attempts == 1
    assert [node.op for node in result.spec.nodes].count("rex.ground@1.0") == 1
    color = next(node for node in result.spec.nodes if node.op == "visual.color_fraction@1.0")
    assert color.params["color"] == "white"
    assert color.params["subject_region"] == [0.0, 0.15, 1.0, 0.7]


def test_clothing_color_compiles_carrier_then_dominant_color_then_person_association():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "穿黑衣的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别穿黑色衣服的人"], "source_span": "黑色",
            "kind": "visual_attribute", "dimension": "color", "value": "black",
            "phrases": ["black"], "region": "upper_body", "carrier": "clothing",
        }], "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(intent, ensure_ascii=False)])
    ).compile("识别穿黑色衣服的人", "image")
    carrier = next(node for node in result.spec.nodes if node.id == "constraint_1_carriers")
    assert carrier.params["targets"][0]["phrases"] == ["clothing"]
    color = next(node for node in result.spec.nodes if node.id == "constraint_1_color")
    assert color.inputs["objects"] == "$constraint_1_carriers"
    assert color.params["selection_mode"] == "dominant"
    association = next(node for node in result.spec.nodes if node.id == "constraint_1_matches")
    assert association.inputs == {
        "subjects": "$candidates", "objects": "$constraint_1_colored_carriers"
    }


def test_color_carrier_normalization_canonicalizes_color_and_removes_carrier_existence_noise():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "穿黑衣的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [
            {"sources": ["识别穿黑色衣服的人"], "source_span": "黑色", "kind": "visual_attribute",
             "dimension": "color", "value": "black", "phrases": ["black clothing"],
             "carrier": "clothing", "region": "whole"},
            {"sources": ["识别穿黑色衣服的人"], "source_span": "穿", "kind": "visual_attribute",
             "dimension": "wearable", "value": "wearing clothing",
             "phrases": ["wearing clothing"], "region": "whole"},
        ], "absent": [],
    }
    DeepSeekPlanner._normalize_catalog_colors(intent, ["识别穿黑色衣服的人"])
    assert intent["required"] == [{
        "sources": ["识别穿黑色衣服的人"], "source_span": "黑色", "kind": "visual_attribute",
        "dimension": "color", "value": "black", "phrases": ["black"],
        "carrier": "clothing", "region": "whole",
    }]


def test_carrier_catalog_generalizes_upper_and_lower_clothing_and_removes_redundant_wearables():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "红色上衣灰色长裤的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [
            {"sources": ["识别穿红色上衣"], "source_span": "穿红色上衣", "kind": "visual_attribute",
             "dimension": "wearable", "value": "shirt", "phrases": ["person wearing a shirt"],
             "region": "upper_body"},
            {"sources": ["识别穿红色上衣"], "source_span": "红色上衣", "kind": "visual_attribute",
             "dimension": "color", "value": "red", "phrases": ["red clothing"],
             "carrier": "shirt", "region": "upper_body"},
            {"sources": ["灰色长裤的人"], "source_span": "长裤", "kind": "visual_attribute",
             "dimension": "wearable", "value": "pants", "phrases": ["person wearing pants"],
             "region": "lower_body"},
            {"sources": ["灰色长裤的人"], "source_span": "灰色长裤", "kind": "visual_attribute",
             "dimension": "color", "value": "gray", "phrases": ["gray pants"],
             "carrier": "pants", "region": "lower_body"},
        ], "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(intent, ensure_ascii=False)])
    ).compile("识别穿红色上衣、灰色长裤的人", "image")
    carriers = [node for node in result.spec.nodes
                if node.id.endswith("_carriers") and node.op == "rex.ground@1.0"]
    assert [node.params["targets"][0]["phrases"] for node in carriers] == [
        ["upper body clothing"], ["lower body clothing"],
    ]
    colors = [node for node in result.spec.nodes if node.op == "visual.color_fraction@1.0"]
    assert [(node.params["color"], node.params["selection_mode"]) for node in colors] == [
        ("red", "fraction"), ("gray", "fraction"),
    ]
    assert not any(node.id.endswith("_objects") for node in result.spec.nodes)
    associations = [node for node in result.spec.nodes if node.id.endswith("_matches")]
    assert [node.params["relation"] for node in associations] == ["best_owner", "best_owner"]


def test_color_constraints_compile_explicit_per_color_default_thresholds():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query",
        "label": "穿白衣的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [{
            "sources": ["识别穿白衣的人"],
            "kind": "color",
            "phrases": ["white"],
            "region": "upper_body",
        }],
        "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("识别穿白衣的人", "image")

    color = next(node for node in result.spec.nodes if node.id == "constraint_1_color")
    assert color.params["min_fraction"] == 0.2


def test_atomic_source_span_resolves_direct_negation_and_double_negation_generically():
    from clients.planner_client import DeepSeekPlanner

    cases = [
        (
            "穿着橙色反光衣且未带安全帽的人",
            "穿着橙色反光衣且未带安全帽的人",
            "穿着橙色反光衣且未带安全帽的人",
            "未带安全帽",
            "absent",
        ),
        (
            "穿着橙色反光衣的人，排除未带安全帽的人",
            "穿着橙色反光衣的人",
            "排除未带安全帽的人",
            "未带安全帽",
            "required",
        ),
        (
            "穿着橙色反光衣的人，去除未带安全帽的人",
            "穿着橙色反光衣的人",
            "去除未带安全帽的人",
            "未带安全帽",
            "required",
        ),
        (
            "正样本是穿着橙色反光衣的人，负样本是未带安全帽的人",
            "正样本是穿着橙色反光衣的人",
            "负样本是未带安全帽的人",
            "未带安全帽",
            "required",
        ),
    ]
    for instruction, positive_source, source, source_span, expected_field in cases:
        predicate = {
            "sources": [source],
            "source_span": source_span,
            "kind": "wearable",
            "phrases": ["wearing safety helmet"],
            "region": "head",
        }
        intent = {
            "mode": "entity_query",
            "label": "目标人员",
            "entity": {"zh": "人", "en": "person", "kind": "person"},
            "required": [
                {
                    "sources": [positive_source], "source_span": "反光衣",
                    "kind": "wearable", "phrases": ["wearing reflective vest"],
                    "region": "upper_body",
                },
                {
                    "sources": [positive_source], "source_span": "橙色",
                    "kind": "color", "phrases": ["orange"],
                    "region": "upper_body",
                },
            ] + ([predicate] if expected_field == "required" else []),
            "absent": [predicate] if expected_field == "absent" else [],
        }
        result = DeepSeekPlanner(
            build_default_registry(),
            client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
        ).compile(instruction, "image")

        assert result.strategy == "llm_intent:entity_query", instruction
        helmet = next(node for node in result.spec.nodes if node.id == "constraint_3_objects")
        if expected_field == "required":
            assert not [node for node in result.spec.nodes if node.op == "logic.not@1.0"]
            assert helmet.inputs["frames"] == "$evidence_frames"
        else:
            assert [node for node in result.spec.nodes if node.op == "logic.not@1.0"]
            assert helmet.inputs["frames"] == "$media"


def test_atomic_polarity_normalizes_llm_field_without_spending_a_repair_call():
    from clients.planner_client import DeepSeekPlanner

    wrong = {
        "mode": "entity_query",
        "label": "目标人员",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["排除未带安全帽的人"],
            "source_span": "未带安全帽",
            "kind": "wearable",
            "phrases": ["wearing safety helmet"],
            "region": "head",
        }],
    }
    fake = FakeClient([json.dumps(wrong, ensure_ascii=False)])

    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "排除未带安全帽的人", "image"
    )

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 1
    assert not [node for node in result.spec.nodes if node.op == "logic.not@1.0"]
    assert result.spec.display_name == "目标人员"


def test_atomic_polarity_restores_adjacent_negation_omitted_from_source_span():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query",
        "label": "戴安全帽的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [],
        "absent": [{
            "sources": ["去除未带安全帽的人"],
            "source_span": "带安全帽",
            "kind": "wearable",
            "phrases": ["wearing safety helmet"],
            "region": "head",
        }],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("去除未带安全帽的人", "image")

    assert result.strategy == "llm_intent:entity_query"
    assert result.attempts == 1
    helmet = next(node for node in result.spec.nodes if node.id == "constraint_1_objects")
    assert helmet.inputs["frames"] == "$evidence_frames"
    assert not [node for node in result.spec.nodes if node.op == "logic.not@1.0"]


def test_semantically_identical_atomic_predicates_are_deduplicated_after_normalization():
    from clients.planner_client import DeepSeekPlanner

    first = {
        "sources": ["去除未带安全帽的人"], "source_span": "未带安全帽",
        "kind": "wearable", "phrases": ["wearing safety helmet"], "region": "head",
    }
    second = {
        "sources": ["去除未带安全帽的人"], "source_span": "带安全帽",
        "kind": "wearable", "phrases": ["wearing safety helmet"], "region": "head",
    }
    intent = {
        "mode": "entity_query", "label": "戴安全帽的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [first], "absent": [second],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("去除未带安全帽的人", "image")

    grounds = [node for node in result.spec.nodes if node.op == "rex.ground@1.0"]
    assert len(grounds) == 2  # base entity + one normalized helmet predicate


def test_double_negation_normalizes_a_contradictory_llm_result_label():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query",
        "label": "穿着橙色反光衣且未带安全帽的人",
        "entity": {"zh": "人", "en": "person", "kind": "person"},
        "required": [
            {
                "sources": ["正样本是穿着橙色反光衣的人"],
                "source_span": "穿着橙色反光衣",
                "kind": "wearable", "phrases": ["wearing reflective vest"],
                "region": "upper_body",
            },
            {
                "sources": ["正样本是穿着橙色反光衣的人"],
                "source_span": "橙色",
                "kind": "color", "phrases": ["orange"],
                "region": "upper_body",
            },
        ],
        "absent": [{
            "sources": ["负样本是未带安全帽的人"],
            "source_span": "未带安全帽",
            "kind": "wearable", "phrases": ["wearing safety helmet"],
            "region": "head",
        }],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("正样本是穿着橙色反光衣的人，负样本是未带安全帽的人", "image")

    assert result.spec.display_name == "穿着橙色反光衣且带安全帽的人"
    assert {
        node.params.get("output_label")
        for node in result.spec.nodes if node.op == "filter.apply@1.0"
    } == {"穿着橙色反光衣且带安全帽的人"}


def test_general_visual_attribute_dimensions_compile_through_fixed_dispatch():
    from clients.planner_client import DeepSeekPlanner

    cases = [
        ("shape", "round", "visual_attribute", "rex.ground@1.0"),
        ("material", "metal", "visual_attribute", "rex.ground@1.0"),
        ("state", "open", "visual_attribute", "rex.ground@1.0"),
        ("size", "small", "geometry", "visual.geometry@1.0"),
        ("position", "left", "geometry", "visual.geometry@1.0"),
    ]
    for dimension, value, kind, expected_op in cases:
        predicate = {
            "sources": [f"识别{value}目标"], "source_span": value,
            "kind": kind, "dimension": dimension, "value": value,
            "phrases": [value], "region": "whole",
        }
        intent = {
            "mode": "entity_query", "label": f"{value}目标",
            "entity": {"zh": "目标", "en": "object", "kind": "object"},
            "required": [predicate], "absent": [],
        }
        result = DeepSeekPlanner(
            build_default_registry(),
            client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
        ).compile(f"识别{value}目标", "image")
        assert expected_op in [node.op for node in result.spec.nodes], dimension


def test_absent_color_is_compiled_as_color_evidence_then_not():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "非红色车辆",
        "entity": {"zh": "车辆", "en": "vehicle", "kind": "vehicle"},
        "required": [],
        "absent": [{
            "sources": ["识别非红色车辆"], "source_span": "非红色",
            "kind": "color", "dimension": "color", "value": "red",
            "phrases": ["red"], "region": "whole",
        }],
    }
    result = DeepSeekPlanner(
        build_default_registry(),
        client=FakeClient([json.dumps(intent, ensure_ascii=False)]),
    ).compile("识别非红色车辆", "image")

    ops = [node.op for node in result.spec.nodes]
    assert "visual.color_fraction@1.0" in ops
    assert "logic.not@1.0" in ops


def test_count_and_spatial_relation_requests_route_to_typed_workflow_intent():
    from clients.planner_client import DeepSeekPlanner

    workflow = {
        "mode": "workflow",
        "goal": "count_filter",
        "entities": [{"id": "cars", "zh": "车辆", "en": "vehicle"}],
        "relations": [{"type": "inside_roi", "subject": "cars", "object": "manual_roi"}],
        "aggregation": {"type": "count", "operator": ">=", "value": 3},
    }
    valid_spec = valid_image_spec()
    fake = FakeClient([
        json.dumps(workflow, ensure_ascii=False),
        json.dumps(valid_spec, ensure_ascii=False),
    ])
    result = DeepSeekPlanner(build_default_registry(), client=fake).compile(
        "统计区域内不少于3辆车", "image"
    )
    assert result.degraded is False
    first_raw = json.loads(result.raw_outputs[0])
    assert first_raw["relations"][0]["type"] == "inside_roi"
    assert first_raw["aggregation"] == {"type": "count", "operator": ">=", "value": 3}


def test_attribute_region_defaults_to_whole_and_size_normalizes_to_geometry():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "小目标",
        "entity": {"zh": "目标", "en": "object", "kind": "object"},
        "required": [{
            "sources": ["识别小目标"], "source_span": "小",
            "kind": "visual_attribute", "dimension": "size", "value": "small",
            "phrases": ["small"],
        }],
        "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(intent, ensure_ascii=False)])
    ).compile("识别小目标", "image")
    geometry = next(node for node in result.spec.nodes if node.op == "visual.geometry@1.0")
    assert geometry.params["dimension"] == "size"


def test_relative_position_cannot_compile_as_absolute_screen_geometry():
    from clients.planner_client import DeepSeekPlanner

    wrong = {
        "mode": "entity_query", "label": "左侧球体",
        "entity": {"zh": "球体", "en": "sphere", "kind": "object"},
        "required": [{
            "sources": ["识别瓶子左侧的球体"], "source_span": "左侧",
            "kind": "geometry", "dimension": "position", "value": "left",
            "phrases": ["left of"],
        }], "absent": [],
    }
    workflow = {
        "mode": "workflow", "goal": "relation_filter",
        "entities": [
            {"id": "sphere", "zh": "球体", "en": "sphere"},
            {"id": "bottle", "zh": "瓶子", "en": "bottle"},
        ],
        "relations": [{"type": "left_of", "subject": "sphere", "object": "bottle"}],
        "aggregation": None,
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([
            json.dumps(wrong, ensure_ascii=False), json.dumps(workflow, ensure_ascii=False),
        ])
    ).compile("识别瓶子左侧的球体", "image")
    assert result.strategy == "llm_intent:workflow"
    relation = next(node for node in result.spec.nodes if node.id == "relation_1")
    assert relation.params["relation"] == "left_of"


def test_spatial_router_distinguishes_absolute_screen_position_from_entity_relation():
    from clients.planner_client import DeepSeekPlanner

    assert DeepSeekPlanner._has_relative_spatial_relation("识别左侧的小型红色方块") is False
    assert DeepSeekPlanner._has_relative_spatial_relation("识别位于紫色瓶子左侧的青色球体") is True
    assert DeepSeekPlanner._has_relative_spatial_relation("识别汽车附近的行人") is True


def test_relative_size_is_evaluated_before_position_reduces_candidate_set():
    from clients.planner_client import DeepSeekPlanner

    intent = {
        "mode": "entity_query", "label": "左侧小物体",
        "entity": {"zh": "物体", "en": "object", "kind": "object"},
        "required": [
            {"sources": ["识别左侧小物体"], "source_span": "左侧", "kind": "geometry",
             "dimension": "position", "value": "left", "phrases": ["left"], "region": "whole"},
            {"sources": ["识别左侧小物体"], "source_span": "小", "kind": "geometry",
             "dimension": "size", "value": "small", "phrases": ["small"], "region": "whole"},
        ], "absent": [],
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(intent, ensure_ascii=False)])
    ).compile("识别左侧小物体", "image")
    geometry = [node for node in result.spec.nodes if node.op == "visual.geometry@1.0"]
    assert [node.params["dimension"] for node in geometry] == ["size", "position"]


def test_typed_spatial_workflow_preserves_atomic_attributes_per_entity():
    from clients.planner_client import DeepSeekPlanner

    workflow = {
        "mode": "workflow", "goal": "relation_filter",
        "entities": [
            {"id": "sphere", "zh": "球体", "en": "sphere", "attributes": [
                {"dimension": "color", "value": "cyan", "phrases": ["cyan"], "region": "whole"}
            ]},
            {"id": "bottle", "zh": "瓶子", "en": "bottle", "attributes": [
                {"dimension": "color", "value": "purple", "phrases": ["purple"], "region": "whole"}
            ]},
        ],
        "relations": [{"type": "left_of", "subject": "sphere", "object": "bottle"}],
        "aggregation": None,
    }
    result = DeepSeekPlanner(
        build_default_registry(), client=FakeClient([json.dumps(workflow, ensure_ascii=False)])
    ).compile("识别位于紫色瓶子左侧的青色球体", "image")
    colors = [node.params["color"] for node in result.spec.nodes
              if node.op == "visual.color_fraction@1.0"]
    assert colors == ["cyan", "purple"]
    relation = next(node for node in result.spec.nodes if node.id == "relation_1")
    assert relation.inputs == {"subjects": "$entity_sphere_filtered_1", "objects": "$entity_bottle_filtered_1"}
