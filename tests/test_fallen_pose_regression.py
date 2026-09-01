from __future__ import annotations

import json
from copy import deepcopy

import cv2
import numpy as np

from core.persistence import RunStore
from core.registry import build_default_registry
from core.runtime import SkillPackageRuntime
from core.semantic import SemanticNormalizer, WorkflowCompiler


INSTRUCTION = "识别视频中是否有人摔倒，持续时间1s。"
FALLEN_LEDGER = {
    "mode": "workflow",
    "target": {
        "concept": "person",
        "source_span": "人",
        "phrases": ["person"],
    },
    "constraints": [
        {
            "kind": "state",
            "value": "fallen",
            "source": "识别视频中是否有人摔倒",
            "source_span": "摔倒",
            "phrases": ["person fallen"],
        },
        {
            "kind": "temporal",
            "value": {"type": "persist", "seconds": 1.0},
            "source": "持续时间1s",
            "source_span": "持续时间1s",
            "phrases": [],
            "temporal": True,
        },
    ],
    "logic": "all",
    "unresolved": [],
}


class StandingOnlyLegacyPhraseRex:
    """Simulates the observed legacy phrase false positive on a standing person."""

    def detect(self, image, phrases):
        if "person" in phrases:
            return [{"phrase": "person", "bbox": [0.2, 0.1, 0.6, 0.9]}]
        if any(
            phrase in {
                "person fallen",
                "fallen person",
                "person who has fallen",
            }
            for phrase in phrases
        ):
            return [{"phrase": "person fallen", "bbox": [0.2, 0.1, 0.6, 0.9]}]
        return []


class TileScopedPoseFalsePositiveRex:
    """Simulates pose hallucination that appears only after tiling context."""

    def detect(self, image, phrases):
        if "person" in phrases:
            return [{"phrase": "person", "bbox": [0.2, 0.1, 0.6, 0.9]}]
        if "person lying on the ground" in phrases and image.width <= 640:
            return [{
                "phrase": "person lying on the ground",
                "bbox": [0.2, 0.1, 0.6, 0.9],
            }]
        return []


def _compile_fallen_instruction():
    semantic_ir = SemanticNormalizer().normalize_ledger(FALLEN_LEDGER, INSTRUCTION)
    return WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=INSTRUCTION,
        requested_accept=["video"],
        skill_id="fallen_pose_regression",
        display_name="人员摔倒",
    )


def _write_standing_video(tmp_path):
    video = tmp_path / "standing.avi"
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (960, 720)
    )
    assert writer.isOpened()
    for _ in range(3):
        writer.write(np.full((720, 960, 3), 255, dtype=np.uint8))
    writer.release()
    return video


def test_fallen_state_ledger_normalizes_to_visible_fallen_or_lying_pose():
    semantic_ir = SemanticNormalizer().normalize_ledger(FALLEN_LEDGER, INSTRUCTION)

    pose = semantic_ir.constraints[0]
    assert pose.kind == "pose"
    assert pose.value == "fallen_or_lying"
    assert pose.phrases == ["person lying on the ground"]


def test_fallen_pose_compiles_without_legacy_standing_false_positive_phrases():
    package = _compile_fallen_instruction()
    phrases = [
        phrase
        for node in package.variants["video"].nodes
        if node.op == "rex.ground@1.1"
        for target in node.params["targets"]
        for phrase in target["phrases"]
    ]

    assert "person lying on the ground" in phrases
    assert not {
        "person fallen",
        "fallen person",
        "person who has fallen",
    } & set(phrases)


def test_temporal_atom_does_not_carry_grounding_evidence_from_planner_leakage():
    ledger = deepcopy(FALLEN_LEDGER)
    ledger["constraints"][1]["phrases"] = ["person fallen"]

    semantic_ir = SemanticNormalizer().normalize_ledger(ledger, INSTRUCTION)

    assert semantic_ir.constraints[1].kind == "temporal"
    assert semantic_ir.constraints[1].phrases == []


def test_pose_evidence_preserves_full_frame_context_instead_of_tiling():
    package = _compile_fallen_instruction()
    variant = package.variants["video"]
    pose_grounding = next(
        node for node in variant.nodes if node.id == "constraint_1_objects"
    )
    assert pose_grounding.op == "objects.filter_by_label@1.0"
    shared_grounding = next(
        node
        for node in variant.nodes
        if node.id == pose_grounding.inputs["objects"].removeprefix("$")
    )

    assert shared_grounding.op == "rex.ground@1.1"
    assert shared_grounding.inputs["frames"] == "$resized"
    assert len([
        node for node in variant.nodes if node.op == "rex.ground@1.1"
    ]) == 1
    assert not any(node.id == "evidence_frames" for node in variant.nodes)


def test_fallen_pose_keeps_a_relaxed_geometry_guard_for_pose_false_positives():
    package = _compile_fallen_instruction()
    nodes = {node.id: node for node in package.variants["video"].nodes}

    geometry = nodes["constraint_1_pose_geometry"]
    combined = nodes["constraint_1_pose_all"]
    assert geometry.op == "visual.geometry@1.0"
    assert geometry.inputs == {"objects": "$candidates"}
    assert geometry.params == {
        "dimension": "aspect_ratio",
        "value": "horizontal",
        "aspect_ratio_threshold": 0.6,
    }
    assert combined.op == "logic.all@1.0"
    assert combined.inputs["conditions"] == [
        "$constraint_1_matches",
        "$constraint_1_pose_geometry",
    ]
    assert nodes["constraint_1_matches"].params == {
        "relation": "mutual_match",
        "threshold": 0.3,
    }


def test_video_yes_no_fall_query_declares_an_immediate_event_output():
    ledger = deepcopy(FALLEN_LEDGER)
    ledger["constraints"] = [ledger["constraints"][0]]
    instruction = "识别视频中是否有人摔倒"
    semantic_ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=["video"],
        skill_id="fall_query_event",
        display_name="人员摔倒",
    )

    variant = package.variants["video"]
    event = next(node for node in variant.nodes if node.op == "event.from_condition@1.0")
    alert = next(node for node in variant.nodes if node.op == "output.alert@1.0")
    assert event.params == {
        "seconds": 0.0,
        "scope": "track",
        "gap_tolerance_seconds": 0.0,
        "trigger_mode": "once",
        "label": "人员摔倒",
    }
    assert alert.inputs == {"events": f"${event.id}"}
    assert variant.outputs["events"] == f"${alert.id}"


def test_video_plain_detection_without_event_intent_remains_detection_only():
    ledger = deepcopy(FALLEN_LEDGER)
    ledger["constraints"] = [ledger["constraints"][0]]
    instruction = "检测视频中的摔倒人员"
    ledger["target"]["source_span"] = "人员"
    ledger["constraints"][0]["source"] = instruction
    semantic_ir = SemanticNormalizer().normalize_ledger(ledger, instruction)
    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=["video"],
        skill_id="fall_detection_only",
        display_name="摔倒人员检测",
    )

    assert "events" not in package.variants["video"].outputs


def test_standing_person_does_not_become_persistent_fall_event_when_legacy_phrase_would_false_positive(
    tmp_path,
):
    package = _compile_fallen_instruction()
    record = SkillPackageRuntime(
        build_default_registry(),
        rex=StandingOnlyLegacyPhraseRex(),
        run_store=RunStore(tmp_path / "runs"),
    ).run(package, package, _write_standing_video(tmp_path))

    events = json.loads((record.run_dir / "events.json").read_text("utf-8"))
    assert events == []


def test_standing_person_does_not_become_event_when_pose_false_positive_is_tile_scoped(
    tmp_path,
):
    package = _compile_fallen_instruction()
    record = SkillPackageRuntime(
        build_default_registry(),
        rex=TileScopedPoseFalsePositiveRex(),
        run_store=RunStore(tmp_path / "runs"),
    ).run(package, package, _write_standing_video(tmp_path))

    events = json.loads((record.run_dir / "events.json").read_text("utf-8"))
    assert events == []
