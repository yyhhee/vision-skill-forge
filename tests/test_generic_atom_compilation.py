from __future__ import annotations

import pytest

from core.registry import build_default_registry
from core.semantic import SemanticNormalizer, WorkflowCompiler
from core.validator import validate_skill_package


def _compile(constraints, instruction="检测目标", target=None, media=None):
    target = target or {"concept": "object", "source_span": "目标", "phrases": ["object"]}
    ledger = {
        "mode": "entity_query",
        "target": target,
        "constraints": constraints,
        "logic": "all",
        "unresolved": [],
    }
    semantic_ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    return WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=media or ["image"],
        skill_id="generic_detector",
        display_name="通用目标",
    )


def _grounding_source(variant, node_id):
    """Resolve a condition selector back to its shared Rex request and targets."""

    nodes = {node.id: node for node in variant.nodes}
    node = nodes[node_id]
    if node.op == "rex.ground@1.1":
        return node, node.params["targets"]
    assert node.op == "objects.filter_by_label@1.0"
    source = nodes[node.inputs["objects"].removeprefix("$")]
    labels = set(node.params["labels"])
    return source, [
        target for target in source.params["targets"]
        if target["label"] in labels
    ]


@pytest.mark.parametrize(
    ("kind", "value", "expected_op"),
    [
        ("color", "blue", "visual.color_fraction@1.0"),
        ("size", "small", "visual.geometry@1.0"),
        ("position", "left", "visual.geometry@1.0"),
    ],
)
def test_closed_set_visual_atoms_compile_to_deterministic_operators(kind, value, expected_op):
    package = _compile(
        [{
            "kind": kind,
            "value": value,
            "source": "检测目标",
            "source_span": "目标",
        }]
    )

    variant = package.select_variant("image")
    bound = variant.atom_bindings["atom_1"]
    assert any(
        node.id in bound and node.op == expected_op for node in variant.nodes
    )
    assert validate_skill_package(package, build_default_registry()) == []


@pytest.mark.parametrize(
    ("kind", "value", "phrases"),
    [
        ("shape", "triangle", ["triangular object"]),
        ("material", "metal", ["metal object"]),
        ("state", "open", ["open object"]),
        ("wearable", "reflective_vest", ["wearing reflective vest"]),
        ("pose", "squatting", ["squatting person"]),
        ("appearance", "damaged", ["damaged object"]),
    ],
)
def test_open_visual_atoms_compile_as_affirmative_evidence_then_association(
    kind, value, phrases
):
    instruction = "检测具有指定属性的目标"
    package = _compile(
        [{
            "kind": kind,
            "value": value,
            "source": instruction,
            "source_span": "指定属性",
            "phrases": phrases,
        }],
        instruction=instruction,
    )

    variant = package.select_variant("image")
    evidence = next(node for node in variant.nodes if node.id == "constraint_1_objects")
    evidence_grounding, evidence_targets = _grounding_source(
        variant, "constraint_1_objects"
    )
    association = next(
        node for node in variant.nodes if node.id == "constraint_1_matches"
    )
    if kind == "pose":
        assert not any(node.id == "evidence_frames" for node in variant.nodes)
        assert evidence_grounding.inputs["frames"] == "$resized"
    else:
        evidence_frames = next(
            node for node in variant.nodes if node.id == "evidence_frames"
        )
        assert evidence_frames.op == "image.tile@1.1"
        assert evidence_frames.inputs == {"frames": "$resized"}
        assert evidence_frames.params == {
            "tile_width": 640,
            "tile_height": 640,
            "overlap_x": 0.2,
            "overlap_y": 0.2,
            "include_full_frame": True,
        }
    assert evidence_grounding.op == "rex.ground@1.1"
    assert evidence_grounding.inputs["frames"] == (
        "$resized" if kind == "pose" else "$evidence_frames"
    )
    expected_phrases = (
        ["object wearing reflective vest"] if kind == "wearable" else phrases
    )
    assert evidence_targets[0]["phrases"] == expected_phrases
    assert association.inputs["subjects"] == "$candidates"
    assert association.inputs["objects"] == "$constraint_1_objects_dedup"
    assert association.params == {"relation": "mutual_match", "threshold": 0.5}
    if kind == "wearable":
        assert variant.atom_bindings["atom_1"] == [
            "evidence_frames",
            "constraint_1_wearable_parts",
            "constraint_1_wearable_parts_dedup",
            "constraint_1_wearable_part_matches",
            "constraint_1_objects",
            "constraint_1_objects_dedup",
            "constraint_1_matches",
            "constraint_1_wearable_present",
        ]
    elif kind == "pose":
        assert variant.atom_bindings["atom_1"] == [
            "constraint_1_objects",
            "constraint_1_objects_dedup",
            "constraint_1_matches",
        ]
    else:
        assert variant.atom_bindings["atom_1"] == [
            "evidence_frames",
            "constraint_1_objects",
            "constraint_1_objects_dedup",
            "constraint_1_matches",
        ]


def test_absent_visual_evidence_uses_full_frame_then_deterministic_not():
    instruction = "检测不是三角形的目标"
    package = _compile(
        [{
            "kind": "shape",
            "value": "triangle",
            "source": instruction,
            "source_span": "不是三角形",
            "phrases": ["triangular object"],
        }],
        instruction=instruction,
    )

    variant = package.select_variant("image")
    nodes = {node.id: node for node in variant.nodes}
    assert "evidence_frames" not in nodes
    grounding, _targets = _grounding_source(variant, "constraint_1_objects")
    assert grounding.inputs["frames"] == "$resized"
    assert nodes["constraint_1_matches"].params == {
        "relation": "mutual_match",
        "threshold": 0.5,
    }
    assert nodes["constraint_1_not"].inputs == {
        "condition": "$constraint_1_matches"
    }


def test_wearable_atom_fuses_part_ownership_and_whole_subject_evidence():
    instruction = "检测未戴安全帽的人"
    package = _compile(
        [{
            "kind": "wearable",
            "value": "safety_helmet",
            "source": instruction,
            "source_span": "未戴安全帽",
            "phrases": ["person wearing safety helmet"],
        }],
        instruction=instruction,
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
    )

    variant = package.select_variant("image")
    nodes = {node.id: node for node in variant.nodes}
    grounding, part_targets = _grounding_source(
        variant, "constraint_1_wearable_parts"
    )
    subject_grounding, subject_targets = _grounding_source(
        variant, "constraint_1_objects"
    )
    assert grounding.id == subject_grounding.id
    assert len([node for node in variant.nodes if node.op == "rex.ground@1.1"]) == 1
    assert part_targets[0]["phrases"] == [
        "safety helmet"
    ]
    assert nodes["constraint_1_wearable_part_matches"].params == {
        "relation": "center_in_subject_region",
        "threshold": 0.1,
        "subject_region": [0.0, 0.0, 1.0, 0.35],
    }
    assert subject_targets[0]["phrases"] == [
        "person wearing safety helmet"
    ]
    assert nodes["constraint_1_matches"].params == {
        "relation": "mutual_match", "threshold": 0.5,
    }
    assert nodes["constraint_1_wearable_present"].inputs == {
        "conditions": [
            "$constraint_1_wearable_part_matches", "$constraint_1_matches"
        ]
    }
    assert nodes["constraint_1_wearable_present"].op == "logic.all@1.0"
    assert nodes["constraint_1_not"].inputs == {
        "condition": "$constraint_1_wearable_present"
    }


def test_required_pose_atoms_are_grounded_once_as_one_complete_subject_predicate():
    instruction = "检测蹲着且双膝弯曲的人"
    package = _compile(
        [
            {
                "kind": "pose",
                "value": "squatting",
                "source": instruction,
                "source_span": "蹲着",
                "phrases": ["squatting"],
            },
            {
                "kind": "pose",
                "value": "knees bent",
                "source": instruction,
                "source_span": "双膝弯曲",
                "phrases": ["knees bent"],
            },
        ],
        instruction=instruction,
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
    )

    variant = package.select_variant("image")
    nodes = {node.id: node for node in variant.nodes}
    grouped = nodes["pose_group_1_objects"]
    grounding, targets = _grounding_source(variant, "pose_group_1_objects")
    assert grounding.inputs["frames"] == "$resized"
    assert targets[0]["phrases"] == [
        "person squatting with knees bent"
    ]
    assert nodes["pose_group_1_matches"].params == {
        "relation": "mutual_match",
        "threshold": 0.5,
    }
    assert "constraint_1_objects" not in nodes
    assert "constraint_2_objects" not in nodes
    assert variant.atom_bindings["atom_1"] == variant.atom_bindings["atom_2"]
    assert "evidence_frames" not in variant.atom_bindings["atom_1"]
    assert nodes["filtered"].inputs["condition"] == "$pose_group_1_matches"


def test_relational_state_evidence_keeps_subject_and_positive_relation_context():
    instruction = "检测臀部无支撑的人"
    package = _compile(
        [{
            "kind": "state",
            "value": "support under hips",
            "source": instruction,
            "source_span": "臀部无支撑",
            "phrases": ["support under hips"],
        }],
        instruction=instruction,
        target={"concept": "person", "source_span": "人", "phrases": ["person"]},
    )

    variant = package.select_variant("image")
    evidence = next(
        node for node in variant.nodes if node.id == "constraint_1_objects"
    )
    _grounding, targets = _grounding_source(variant, "constraint_1_objects")
    assert targets[0]["phrases"] == [
        "person with support under hips"
    ]


def test_non_affirmative_grounding_phrase_is_rejected_before_workflow_compilation():
    instruction = "检测没有安全帽的人"
    ledger = {
        "mode": "entity_query",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [{
            "kind": "wearable",
            "value": "safety_helmet",
            "source": instruction,
            "source_span": "没有安全帽",
            "phrases": ["person without safety helmet"],
        }],
        "logic": "all",
        "unresolved": [],
    }

    with pytest.raises(Exception, match="affirmative"):
        SemanticNormalizer().normalize_ledger(ledger, instruction)


def test_unknown_closed_set_color_becomes_unresolved_not_open_grounding():
    instruction = "检测米白色目标"
    semantic_ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {"concept": "object", "source_span": "目标", "phrases": ["object"]},
            "constraints": [{
                "kind": "color", "value": "米白色", "source": instruction,
                "source_span": "米白色",
            }],
            "logic": "all",
        },
        instruction,
    )

    assert semantic_ir.unresolved[0].reason.startswith("unknown color")
