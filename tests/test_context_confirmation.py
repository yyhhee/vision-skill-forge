from __future__ import annotations

import json
from pathlib import Path

import core.preset_factory as preset_factory
from core.registry import build_default_registry


def _workflow():
    return [
        {"id": "media", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}},
        {"id": "resized", "op": "image.resize@1.1", "inputs": {"frames": "$media"}, "params": {"mode": "identity"}},
        {"id": "candidates_raw", "op": "rex.ground@1.1", "inputs": {"frames": "$resized"}, "params": {"targets": [{"label": "垃圾", "phrases": ["small litter"]}]}},
        {"id": "candidates", "op": "objects.deduplicate@1.0", "inputs": {"objects": "$candidates_raw"}, "params": {"metric": "ios", "threshold": 0.5, "keep": "first"}},
        {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": "$resized", "objects": "$candidates"}, "params": {}},
    ]


def test_context_confirmation_is_explicit_reconfigurable_and_removable():
    assert hasattr(preset_factory, "apply_context_confirmation")
    nodes, outputs = preset_factory.apply_context_confirmation(
        _workflow(),
        {"objects": "$candidates"},
        candidate_phrases=["small litter"],
        confirmation_phrases=["visible discarded item on the ground"],
        padding_fraction=0.8,
        crop_long_side=768,
    )

    by_id = {node["id"]: node for node in nodes}
    assert by_id["context_confirmation_crops"]["params"]["padding_fraction"] == 0.8
    assert by_id["context_confirmation_crop_resized"]["params"]["long_side"] == 768
    assert by_id["context_confirmation_evidence_raw"]["params"]["targets"] == [{
        "label": "二次可见性确认",
        "phrases": ["visible discarded item on the ground"],
    }]
    assert by_id["draw"]["inputs"]["objects"] == "$context_confirmation_deduplicated"
    assert outputs["objects"] == "$context_confirmation_deduplicated"

    updated_nodes, updated_outputs = preset_factory.apply_context_confirmation(
        nodes,
        outputs,
        candidate_phrases=["small litter"],
        confirmation_phrases=["clearly visible loose waste item"],
        padding_fraction=1.0,
        crop_long_side=640,
    )
    assert sum(node["id"] == "context_confirmation_evidence_raw" for node in updated_nodes) == 1
    assert next(node for node in updated_nodes if node["id"] == "context_confirmation_evidence_raw")["params"]["targets"][0]["phrases"] == ["clearly visible loose waste item"]

    updated_nodes.insert(
        next(index for index, node in enumerate(updated_nodes) if node["id"] == "draw"),
        {"id": "count", "op": "measure.count@1.0", "inputs": {"entities": "$context_confirmation_deduplicated"}, "params": {"scope": "frame"}},
    )
    reapplied_nodes, _ = preset_factory.apply_context_confirmation(
        updated_nodes, updated_outputs,
        candidate_phrases=["small litter"],
        confirmation_phrases=["clearly visible loose waste item"],
    )
    assert next(node for node in reapplied_nodes if node["id"] == "count")["inputs"]["entities"] == "$context_confirmation_deduplicated"

    restored_nodes, restored_outputs = preset_factory.apply_context_confirmation(
        updated_nodes, updated_outputs, enabled=False
    )
    assert not any(node["id"].startswith("context_confirmation_") for node in restored_nodes)
    assert next(node for node in restored_nodes if node["id"] == "draw")["inputs"]["objects"] == "$candidates"
    assert restored_outputs["objects"] == "$candidates"


def test_controller_exposes_context_confirmation_as_editable_effective_configuration(tmp_path):
    from app_v2 import V2AppController

    assert hasattr(V2AppController, "apply_context_confirmation_control")
    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=None,
        rex=None,
    )
    original = (
        Path(__file__).resolve().parents[1]
        / "presets_v2"
        / "P11_service_area_garbage.json"
    ).read_text(encoding="utf-8")

    updated = controller.apply_context_confirmation_control(
        original,
        "image",
        True,
        ["垃圾容器"],
        "complete trash bin with visible container body",
        0.75,
        768,
    )
    variant_nodes = json.loads(updated)["variants"]["image"]["nodes"]
    nodes = {node["id"] for node in variant_nodes}
    assert "context_confirmation_evidence_raw" in nodes
    assert sum(node.startswith("context_confirmation_") for node in nodes) == 10
    count = next(node for node in variant_nodes if node["id"] == "count")
    assert count["inputs"]["entities"] == "$context_confirmation_deduplicated"
