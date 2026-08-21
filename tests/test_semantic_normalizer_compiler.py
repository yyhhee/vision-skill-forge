from __future__ import annotations

import pytest

from core.registry import build_default_registry
from core.semantic import SemanticNormalizer, SemanticValidationError, WorkflowCompiler
from core.validator import validate_skill_package


PARAPHRASES = [
    "检测穿红色衣服、灰色裤子的人",
    "检测穿红色上衣、灰色裤子的人。",
    "识别穿红色上衣、灰色长裤的人。",
    "找出上身红衣且下身灰裤的人员。",
    "把红上衣并且穿灰裤的人框出来。",
]


def test_clothing_paraphrases_normalize_to_identical_semantic_ir():
    normalizer = SemanticNormalizer()

    results = [normalizer.normalize_text(text) for text in PARAPHRASES]

    assert {item.semantic_hash for item in results} == {results[0].semantic_hash}
    signatures = [
        (
            item.mode,
            item.target.concept,
            tuple(item.target.phrases),
            item.logic,
            tuple(
                (constraint.kind, constraint.value, constraint.carrier, constraint.polarity)
                for constraint in item.constraints
            ),
        )
        for item in results
    ]
    assert signatures == [signatures[0]] * len(PARAPHRASES)
    for instruction, item in zip(PARAPHRASES, results):
        assert item.target.source_span in instruction
        assert all(constraint.source_span in instruction for constraint in item.constraints)
    assert [
        (constraint.kind, constraint.value, constraint.carrier, constraint.polarity)
        for constraint in results[0].constraints
    ] == [
        ("color", "red", "upper_body_clothing", "required"),
        ("color", "gray", "lower_body_clothing", "required"),
    ]

def test_workflow_compiler_grounds_color_carriers_globally_then_assigns_best_owner():
    semantic_ir = SemanticNormalizer().normalize_text(PARAPHRASES[0])

    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=PARAPHRASES[0],
        requested_accept=["image", "video"],
        skill_id="red_top_gray_pants_person",
        display_name="红上衣灰裤人员",
    )

    assert package.input.accept == ["image", "video"]
    assert validate_skill_package(package, build_default_registry()) == []
    for media_type in ("image", "video"):
        variant = package.select_variant(media_type)
        nodes = {node.id: node for node in variant.nodes}
        color_nodes = [
            node for node in variant.nodes
            if node.op == "visual.color_fraction@1.0"
        ]
        assert len(color_nodes) == 2
        assert [node.inputs["objects"] for node in color_nodes] == [
            "$constraint_1_carriers", "$constraint_2_carriers"
        ]
        assert all(node.params["subject_region"] == [0.0, 0.0, 1.0, 1.0] for node in color_nodes)
        assert "constraint_1_crops" not in nodes
        assert "constraint_2_crops" not in nodes
        assert nodes["constraint_1_carriers_raw"].inputs["frames"] == "$resized"
        assert nodes["constraint_2_carriers_raw"].inputs["frames"] == "$resized"
        assert nodes["constraint_1_matches"].params == {
            "relation": "best_owner", "threshold": 0.1,
        }
        assert nodes["constraint_2_matches"].params == {
            "relation": "best_owner", "threshold": 0.1,
        }
        combined = next(node for node in variant.nodes if node.id == "constraints_all")
        assert combined.op == "logic.all@1.0"
        assert combined.inputs["conditions"] == [
            "$constraint_1_matches",
            "$constraint_2_matches",
        ]
        assert variant.atom_bindings == {
            "atom_1": [
                "constraint_1_carriers_raw", "constraint_1_carriers",
                "constraint_1_color", "constraint_1_colored_carriers",
                "constraint_1_matches",
            ],
            "atom_2": [
                "constraint_2_carriers_raw", "constraint_2_carriers",
                "constraint_2_color", "constraint_2_colored_carriers",
                "constraint_2_matches",
            ],
        }
        final_filter = next(node for node in variant.nodes if node.id == "filtered")
        assert final_filter.inputs == {
            "objects": "$candidates",
            "condition": "$constraints_all",
        }


def test_unknown_carrier_is_explicitly_unresolved_instead_of_falling_back_to_person_color():
    ledger = {
        "mode": "entity_query",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [
            {
                "kind": "color",
                "value": "red",
                "source_span": "红色护具",
                "carrier": "护具",
                "carrier_span": "护具",
                "polarity": "required",
            }
        ],
        "logic": "all",
    }

    semantic_ir = SemanticNormalizer().normalize_ledger(ledger, "识别穿红色护具的人")

    assert semantic_ir.unresolved[0].source_span == "护具"
    with pytest.raises(SemanticValidationError, match="unresolved semantics"):
        WorkflowCompiler(build_default_registry()).compile(
            semantic_ir,
            original_instruction="识别穿红色护具的人",
            requested_accept=["image"],
            skill_id="red_guard_person",
            display_name="红色护具人员",
        )


def test_normalizer_rejects_an_invented_source_span():
    ledger = {
        "mode": "entity_query",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [
            {
                "kind": "pose",
                "value": "running",
                "source_span": "奔跑",
                "phrases": ["running"],
                "polarity": "required",
            }
        ],
        "logic": "all",
    }

    with pytest.raises(SemanticValidationError, match="source_span is not present"):
        SemanticNormalizer().normalize_ledger(ledger, "检测站立的人")


@pytest.mark.parametrize(
    ("instruction", "expected_polarity"),
    [
        ("穿橙色反光衣且未戴安全帽的人", "absent"),
        ("穿橙色反光衣的人，排除未戴安全帽的人", "required"),
        ("穿橙色反光衣的人，去除未戴安全帽的人", "required"),
        ("正样本是穿橙色反光衣的人，负样本是未戴安全帽的人", "required"),
    ],
)
def test_final_polarity_is_determined_by_atomic_xor_collection_negation(
    instruction, expected_polarity
):
    semantic_ir = SemanticNormalizer().normalize_text(instruction)

    helmet = next(item for item in semantic_ir.constraints if item.value == "safety_helmet")
    assert helmet.polarity == expected_polarity


def test_helmet_exclusion_kind_is_normalized_to_wearable_predicate():
    instruction = "穿着橙色反光衣且未戴安全帽的人。"
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "person", "source_span": "人", "phrases": ["person"]
            },
            "constraints": [{
                "kind": "entity_exclusion",
                "value": "hard hat",
                "source": "穿着橙色反光衣且未戴安全帽的人",
                "source_span": "未戴安全帽",
                "phrases": ["hard hat"],
            }],
            "logic": "all",
            "unresolved": [],
        },
        instruction,
    )

    helmet = ir.constraints[0]
    assert helmet.kind == "wearable"
    assert helmet.value == "safety_helmet"
    assert helmet.phrases == ["person wearing safety helmet"]
    assert helmet.polarity == "absent"


@pytest.mark.parametrize(
    ("instruction", "span", "phrase", "expected_phrase", "expected_polarity"),
    [
        (
            "检测未佩戴防护手套的工人。",
            "未佩戴防护手套",
            "protective gloves",
            "worker wearing protective gloves",
            "absent",
        ),
        (
            "检测没带护目镜的工人。",
            "没带护目镜",
            "safety goggles",
            "worker wearing safety goggles",
            "absent",
        ),
        (
            "检测工人，排除穿反光背心的人。",
            "穿反光背心",
            "person wearing reflective vest",
            "worker wearing reflective vest",
            "absent",
        ),
        (
            "检测工人，排除未系安全绳的人。",
            "未系安全绳",
            "safety harness",
            "worker wearing safety harness",
            "required",
        ),
    ],
)
def test_subject_wearable_exclusions_are_normalized_by_grammar_not_item_name(
    instruction, span, phrase, expected_phrase, expected_polarity
):
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "worker", "source_span": "工人", "phrases": ["worker"]
            },
            "constraints": [{
                "kind": "entity_exclusion",
                "value": phrase,
                "source": instruction.rstrip("。"),
                "source_span": span,
                "phrases": [phrase],
            }],
            "logic": "all",
            "unresolved": [],
        },
        instruction,
    )

    wearable = ir.constraints[0]
    assert wearable.kind == "wearable"
    assert wearable.phrases == [expected_phrase]
    assert wearable.polarity == expected_polarity


def test_independent_entity_exclusion_is_not_retyped_as_wearable():
    instruction = "检测轿车和人，排除货车。"
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "object",
                "source_span": "轿车和人",
                "phrases": ["passenger car", "person"],
            },
            "constraints": [{
                "kind": "entity_exclusion",
                "value": "truck",
                "source": "排除货车",
                "source_span": "货车",
                "phrases": ["truck"],
            }],
            "logic": "all",
            "unresolved": [],
        },
        instruction,
    )

    assert ir.constraints[0].kind == "entity_exclusion"


def test_open_english_part_carrier_is_compiled_without_task_specific_catalog_entry():
    instruction = "识别穿着黄色反光衣的人。"
    ledger = {
        "mode": "entity_query",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [
            {
                "kind": "color",
                "value": "yellow",
                "source": "识别穿着黄色反光衣的人",
                "source_span": "黄色反光衣",
                "carrier": "reflective vest",
                "carrier_span": "反光衣",
                "phrases": ["yellow reflective vest"],
            },
            {
                "kind": "wearable",
                "value": "reflective_vest",
                "source": "识别穿着黄色反光衣的人",
                "source_span": "穿着黄色反光衣",
                "phrases": ["wearing reflective vest"],
            },
        ],
        "logic": "all",
        "unresolved": [],
    }

    ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="yellow_reflective_person",
        display_name="黄色反光衣人员",
    )

    assert ir.constraints[0].carrier == "reflective vest"
    carrier_ground = next(
        node
        for node in package.variants["image"].nodes
        if node.id == "constraint_1_carriers_raw"
    )
    assert carrier_ground.params["targets"][0]["phrases"] == ["reflective vest"]


def test_compound_color_phrase_recovers_specific_open_carrier_from_visible_phrase():
    instruction = "识别穿着黄色反光衣的人。"
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "person", "source_span": "人", "phrases": ["person"]
            },
            "constraints": [{
                "kind": "color",
                "value": "yellow",
                "source": "识别穿着黄色反光衣的人",
                "source_span": "黄色反光衣",
                "carrier": "clothing",
                "carrier_span": "反光衣",
                "phrases": ["yellow reflective vest"],
            }],
            "logic": "all",
            "unresolved": [],
        },
        instruction,
    )

    assert ir.constraints[0].carrier == "reflective vest"


def test_generic_clothing_is_upper_body_when_same_clause_has_pants_color():
    instruction = "区域1有穿红色衣服、灰色裤子的人。"
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "workflow",
            "target": {
                "concept": "person", "source_span": "人", "phrases": ["person"]
            },
            "constraints": [
                {
                    "kind": "color", "value": "red",
                    "source": "区域1有穿红色衣服、灰色裤子的人",
                    "source_span": "红色衣服", "carrier": "clothing",
                    "carrier_span": "衣服", "phrases": ["red clothing"],
                },
                {
                    "kind": "color", "value": "gray",
                    "source": "区域1有穿红色衣服、灰色裤子的人",
                    "source_span": "灰色裤子", "carrier": "lower_body_clothing",
                    "carrier_span": "裤子", "phrases": ["gray pants"],
                },
            ],
            "logic": "all", "unresolved": [],
        },
        instruction,
    )

    assert [item.carrier for item in ir.constraints] == [
        "upper_body_clothing", "lower_body_clothing"
    ]


def test_base_entity_named_as_color_carrier_falls_back_to_target_box_and_reports_count():
    instruction = "识别白色车数量。"
    ledger = {
        "mode": "entity_query",
        "target": {"concept": "car", "source_span": "白色车", "phrases": ["white car"]},
        "constraints": [
            {
                "kind": "color",
                "value": "white",
                "source": instruction,
                "source_span": "白色",
                "carrier": "car",
                "carrier_span": "车",
                "phrases": ["white"],
            },
            {
                "kind": "quantity",
                "value": {"measure": "count"},
                "source": instruction,
                "source_span": "数量",
                "phrases": [],
            },
        ],
        "logic": "all",
        "unresolved": [],
    }

    ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="white_car_count",
        display_name="白色车计数",
    )

    assert ir.target.phrases == ["car"]
    color = next(item for item in ir.constraints if item.kind == "color")
    assert color.carrier is None
    nodes = {node.id: node for node in package.variants["image"].nodes}
    assert nodes["constraint_1_color_entity"].params["targets"][0]["phrases"] == [
        "white car"
    ]
    assert nodes["constraint_1_color_entity_matches"].params == {
        "relation": "mutual_match", "threshold": 0.5,
    }
    assert nodes["constraint_1_color_all"].inputs["conditions"] == [
        "$constraint_1_color", "$constraint_1_color_entity_matches"
    ]
    assert nodes["filtered"].inputs["condition"] == "$constraint_1_color_all"
    assert "measure.count@1.0" in [node.op for node in package.variants["image"].nodes]


def test_color_leaked_into_target_concept_is_removed_before_dual_color_evidence():
    instruction = "识别白色车数量。"
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "white car",
                "source_span": "白色车",
                "phrases": ["car"],
            },
            "constraints": [
                {
                    "kind": "color",
                    "value": "white",
                    "source": instruction,
                    "source_span": "白色",
                    "phrases": ["white"],
                },
                {
                    "kind": "quantity",
                    "value": {"measure": "count"},
                    "source": instruction,
                    "source_span": "数量",
                    "phrases": ["white cars"],
                },
            ],
            "logic": "all",
            "unresolved": [],
        },
        instruction,
    )
    package = WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="white_car_count",
        display_name="白色车计数",
    )

    assert ir.target.concept == "car"
    entity = next(
        node for node in package.variants["image"].nodes
        if node.id == "constraint_1_color_entity"
    )
    assert entity.params["targets"][0]["phrases"] == ["white car"]


def test_omitted_collection_exclusion_is_rejected_as_incomplete_semantics():
    instruction = "检测轿车、客车、人，排除货车、面包车。"
    incomplete = {
        "mode": "entity_query",
        "target": {
            "concept": "object",
            "source_span": "轿车、客车、人",
            "phrases": ["passenger car", "coach bus", "person"],
        },
        "constraints": [],
        "logic": "all",
        "unresolved": [],
    }

    with pytest.raises(SemanticValidationError, match="exclusion clause is not covered"):
        SemanticNormalizer().normalize_ledger(incomplete, instruction)


def test_generic_entity_exclusion_uses_global_positive_evidence_and_negated_mutual_match():
    instruction = "检测轿车、客车、人，排除货车、面包车。"
    ledger = {
        "mode": "entity_query",
        "target": {
            "concept": "object",
            "source_span": "轿车、客车、人",
            "phrases": ["passenger car", "coach bus", "person"],
        },
        "constraints": [
            {
                "kind": "entity_exclusion",
                "value": ["truck", "van"],
                "source": "排除货车、面包车",
                "source_span": "货车、面包车",
                "phrases": ["truck", "van"],
            }
        ],
        "logic": "all",
        "unresolved": [],
    }

    ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="road_users_without_trucks",
        display_name="轿车客车人员",
    )
    variant = package.variants["image"]

    exclusion = ir.constraints[0]
    assert exclusion.polarity == "absent"
    assert exclusion.kind == "entity_exclusion"
    nodes = {node.id: node for node in variant.nodes}
    assert "constraint_1_crops" not in nodes
    assert nodes["constraint_1_objects"].inputs["frames"] == "$resized"
    assert nodes["constraint_1_matches"].params == {
        "relation": "mutual_match", "threshold": 0.5,
    }
    assert nodes["constraint_1_not"].inputs == {
        "condition": "$constraint_1_matches"
    }
    assert nodes["filtered"].inputs["condition"] == "$constraint_1_not"


def test_whole_subject_pose_evidence_uses_overlap_while_part_carriers_use_best_owner():
    instruction = "检测正在蹲下、双膝弯曲的人。"
    ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "person",
                "source_span": "人",
                "phrases": ["person"],
            },
            "constraints": [
                {
                    "kind": "pose",
                    "value": "squatting",
                    "source": instruction,
                    "source_span": "正在蹲下",
                    "phrases": ["person squatting"],
                },
                {
                    "kind": "pose",
                    "value": "knees_bent",
                    "source": instruction,
                    "source_span": "双膝弯曲",
                    "phrases": ["knees bent"],
                },
            ],
            "logic": "all",
            "unresolved": [],
        },
        instruction,
    )

    package = WorkflowCompiler(build_default_registry()).compile(
        ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="squatting_person",
        display_name="蹲下人员",
    )
    nodes = {node.id: node for node in package.variants["image"].nodes}

    assert nodes["pose_group_1_matches"].params == {
        "relation": "mutual_match",
        "threshold": 0.5,
    }


@pytest.mark.parametrize(
    "span",
    ["不少于4辆", "不低于4辆", "不超过4辆", "不高于4辆", "不等于4辆"],
)
def test_numeric_comparison_negation_words_do_not_flip_constraint_to_absent(span):
    instruction = f"检测车辆数量{span}。"
    ledger = {
        "mode": "entity_query",
        "target": {"concept": "vehicle", "source_span": "车辆", "phrases": ["vehicle"]},
        "constraints": [
            {
                "kind": "quantity",
                "value": {"measure": "count"},
                "source": instruction,
                "source_span": span,
                "phrases": [],
            }
        ],
        "logic": "all",
        "unresolved": [],
    }

    ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    assert ir.constraints[0].polarity == "required"


def test_explicit_quantity_word_cannot_be_silently_omitted_from_ledger():
    instruction = "识别白色车数量。"
    incomplete = {
        "mode": "entity_query",
        "target": {"concept": "car", "source_span": "白色车", "phrases": ["car"]},
        "constraints": [
            {
                "kind": "color",
                "value": "white",
                "source": instruction,
                "source_span": "白色",
                "phrases": ["white"],
            }
        ],
        "logic": "all",
        "unresolved": [],
    }

    with pytest.raises(SemanticValidationError, match="quantity semantics are not covered"):
        SemanticNormalizer().normalize_ledger(incomplete, instruction)


def test_numbered_regions_repair_position_and_misnested_quantity_grouping():
    instruction = "区域1有穿红色衣服、灰色裤子的人，区域2中人的数量大于2，则发出告警。"
    ledger = {
        "mode": "workflow",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [
            {
                "kind": "position", "value": "region1",
                "source": "区域1有穿红色衣服、灰色裤子的人", "source_span": "区域1",
            },
            {
                "kind": "quantity",
                "value": {"measure": "count", "operator": ">", "value": 2},
                "group_by": "named_region", "region_role": "region2",
                "source": "区域2中人的数量大于2", "source_span": "人的数量大于2",
            },
        ],
        "logic": "all",
        "unresolved": [{"source_span": "区域1", "reason": "unknown position: region1"}],
    }

    ir = SemanticNormalizer().normalize_ledger(ledger, instruction)

    assert ir.unresolved == []
    assert not any(item.kind == "position" for item in ir.constraints)
    roles = {
        item.value["semantic_role"]
        for item in ir.constraints
        if item.kind == "region_requirement"
    }
    assert roles == {"region1", "region2"}
    quantity = next(item for item in ir.constraints if item.kind == "quantity")
    assert quantity.value["group_by"] == "named_region"
    assert quantity.value["region_role"] == "region2"


def test_realistic_color_paraphrase_ledgers_share_hash_despite_nonexecuted_phrase_synonyms():
    instructions_and_ledgers = [
        (
            "检测穿红色上衣、灰色裤子的人。",
            {
                "mode": "direct_grounding",
                "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
                "constraints": [
                    {"kind": "color", "value": "red", "source": "检测穿红色上衣", "source_span": "红色上衣", "carrier": "upper_body_clothing", "carrier_span": "上衣", "phrases": ["red upper body clothing"]},
                    {"kind": "color", "value": "gray", "source": "灰色裤子的人", "source_span": "灰色裤子", "carrier": "lower_body_clothing", "carrier_span": "裤子", "phrases": ["gray pants"]},
                ],
                "logic": "all",
                "unresolved": [],
            },
        ),
        (
            "识别穿红色上衣、灰色长裤的人。",
            {
                "mode": "entity_query",
                "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
                "constraints": [
                    {"kind": "color", "value": "red", "source": "识别穿红色上衣", "source_span": "红色上衣", "carrier": "upper_body_clothing", "carrier_span": "上衣", "phrases": ["red top"]},
                    {"kind": "color", "value": "gray", "source": "灰色长裤的人", "source_span": "灰色长裤", "carrier": "lower_body_clothing", "carrier_span": "长裤", "phrases": ["gray trousers"]},
                ],
                "logic": "all",
                "unresolved": [],
            },
        ),
    ]

    normalized = [
        SemanticNormalizer().normalize_ledger(ledger, instruction)
        for instruction, ledger in instructions_and_ledgers
    ]

    assert normalized[0].semantic_hash == normalized[1].semantic_hash
    assert normalized[0].mode == normalized[1].mode == "entity_query"
