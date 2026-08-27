from __future__ import annotations

import hashlib
import json

import cv2
import numpy as np
import pytest
from PIL import Image

from core.persistence import PackageStore, RunStore
from core.registry import build_default_registry
from core.runtime import SkillPackageRuntime
from core.schema import SkillPackage


class OneBoxRex:
    def __init__(self):
        self.calls = 0

    def detect(self, image, phrases):
        self.calls += 1
        return [{"phrase": phrases[0], "bbox": [0.1, 0.2, 0.5, 0.8]}]


def _package() -> SkillPackage:
    def nodes(media_type: str):
        if media_type == "image":
            start = [
                {"id": "media", "op": "media.image@1.0", "inputs": {"media": "$input"}, "params": {}}
            ]
            frames = "$media"
        else:
            start = [
                {"id": "media", "op": "media.video@1.0", "inputs": {"media": "$input"}, "params": {}},
                {"id": "frames", "op": "video.sample@1.0", "inputs": {"video": "$media"}, "params": {"mode": "fps", "fps": 1.0}},
            ]
            frames = "$frames"
        return start + [
            {"id": "objects", "op": "rex.ground@1.0", "inputs": {"frames": frames}, "params": {"targets": [{"label": "人员", "phrases": ["person"]}]}},
            {"id": "draw", "op": "output.draw@1.0", "inputs": {"frames": frames, "objects": "$objects"}, "params": {}},
        ]

    return SkillPackage.model_validate(
        {
            "schema_version": "2.0",
            "skill_id": "person_detector",
            "version": 1,
            "display_name": "人员检测",
            "original_instruction": "检测人员",
            "compile_status": "compiled",
            "input": {"requested_accept": ["image", "video"], "accept": ["image", "video"]},
            "semantic_ir": {
                "schema_version": "1.0",
                "mode": "direct_grounding",
                "target": {"concept": "person", "source_span": "人员", "phrases": ["person"]},
                "constraints": [],
                "logic": "all",
                "unresolved": [],
                "semantic_hash": "a" * 64,
            },
            "variants": {
                "image": {"media_type": "image", "nodes": nodes("image"), "outputs": {"media": "$draw", "objects": "$objects"}},
                "video": {"media_type": "video", "nodes": nodes("video"), "outputs": {"media": "$draw", "objects": "$objects"}},
            },
        }
    )


def test_package_store_versions_v2_packages_without_losing_variants(tmp_path):
    store = PackageStore(tmp_path / "skills")

    first = store.save(_package())
    second = store.save(_package())
    loaded = store.load("person_detector", 2)

    assert first.name == "1.json"
    assert second.name == "2.json"
    assert set(loaded.variants) == {"image", "video"}
    assert loaded.version == 2


def test_package_runtime_selects_image_variant_and_persists_v2_explanations(tmp_path):
    media = tmp_path / "input.jpg"
    Image.new("RGB", (80, 40), "white").save(media)
    rex = OneBoxRex()

    record = SkillPackageRuntime(
        build_default_registry(), rex=rex, run_store=RunStore(tmp_path / "runs")
    ).run(_package(), _package(), media)

    assert record.media_type == "image"
    assert record.variant == "image"
    assert rex.calls == 1
    assert {"semantic_ir.json", "result.json"} <= {
        path.name for path in record.run_dir.iterdir()
    }
    assert {
        "media_asset.json",
        "preprocessing_summary.json",
        "configuration_slot_summary.json",
        "constraint_summary.json",
    } <= {path.name for path in record.run_dir.iterdir()}
    result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
    assert result["task_target"] == "检测人员"
    assert result["normalized_target"] == "person"
    assert result["semantic_hash"] == "a" * 64
    assert result["media_type"] == "image"
    assert result["actual_rex_phrases"] == ["person"]
    assert len(result["detections"]) == 1
    assert result["detections"][0]["bbox"] == [0.1, 0.2, 0.5, 0.8]
    assert result["tracks"] == []
    assert result["constraint_summary"] == []
    assert result["media_policy"]["sampled_frame_count"] == 1
    assert result["media_policy"]["rex_call_count"] == 1
    assert result["media_policy"]["warnings"] == []
    assert result["artifacts"]["annotated_media"].endswith("annotated.jpg")
    assert result["media_sha256"] == hashlib.sha256(media.read_bytes()).hexdigest()
    assert result["rex_model"] == "OneBoxRex"
    assert {"detections.json", "tracks.json", "events.json", "trace.json"} <= {
        path.name for path in record.run_dir.iterdir()
    }
    metadata = json.loads((record.run_dir / "run.json").read_text("utf-8"))
    assert metadata["media_sha256"] == result["media_sha256"]
    assert metadata["rex_model"] == "OneBoxRex"
    media_asset = json.loads(
        (record.run_dir / "media_asset.json").read_text("utf-8")
    )
    assert media_asset["width"] == 80
    assert media_asset["height"] == 40
    assert media_asset["asset_id"] == result["media_sha256"]
    preprocessing = json.loads(
        (record.run_dir / "preprocessing_summary.json").read_text("utf-8")
    )
    assert preprocessing["media_type"] == "image"
    assert [item["operator"] for item in preprocessing["nodes"]] == []
    assert json.loads(
        (record.run_dir / "configuration_slot_summary.json").read_text("utf-8")
    ) == []
    assert result["artifacts"]["media_asset"].endswith("media_asset.json")
    assert result["artifacts"]["preprocessing_summary"].endswith(
        "preprocessing_summary.json"
    )
    assert result["artifacts"]["configuration_slot_summary"].endswith(
        "configuration_slot_summary.json"
    )
    assert result["artifacts"]["constraint_summary"].endswith(
        "constraint_summary.json"
    )


def test_package_runtime_deduplicates_aliases_of_the_same_entity_output(tmp_path):
    media = tmp_path / "input.jpg"
    Image.new("RGB", (80, 40), "white").save(media)
    package = _package()
    package.variants["image"].outputs["matched_people"] = "$objects"

    record = SkillPackageRuntime(
        build_default_registry(),
        rex=OneBoxRex(),
        run_store=RunStore(tmp_path / "runs"),
    ).run(package, package, media)

    detections = json.loads(
        (record.run_dir / "detections.json").read_text("utf-8")
    )
    metadata = json.loads((record.run_dir / "run.json").read_text("utf-8"))
    assert len(detections) == 1
    assert metadata["object_count"] == 1


def test_package_runtime_runs_effective_video_when_generated_baseline_lacks_video(
    tmp_path,
):
    """The generated package is audit data; Effective is the executable contract."""
    video = tmp_path / "input.avi"
    writer = cv2.VideoWriter(
        str(video), cv2.VideoWriter_fourcc(*"MJPG"), 2.0, (80, 40)
    )
    assert writer.isOpened()
    for _ in range(2):
        writer.write(np.full((40, 80, 3), 255, dtype=np.uint8))
    writer.release()

    generated_data = _package().model_dump(mode="json")
    generated_data["input"]["requested_accept"] = ["image"]
    generated_data["input"]["accept"] = ["image"]
    generated_data["variants"] = {"image": generated_data["variants"]["image"]}
    generated = SkillPackage.model_validate(generated_data)
    effective = _package()

    record = SkillPackageRuntime(
        build_default_registry(), rex=OneBoxRex(), run_store=RunStore(tmp_path / "runs")
    ).run(generated, effective, video)

    assert record.media_type == "video"
    assert record.variant == "video"
    assert record.annotated_media and record.annotated_media.suffix == ".mp4"


def test_runtime_persists_measurements_regions_and_directions_as_result_artifacts(tmp_path):
    media = tmp_path / "input.jpg"
    Image.new("RGB", (100, 60), "white").save(media)
    data = _package().model_dump(mode="json")
    variant = data["variants"]["image"]
    draw = next(node for node in variant["nodes"] if node["id"] == "draw")
    draw_index = variant["nodes"].index(draw)
    extra_nodes = [
        {
            "id": "count",
            "op": "measure.count@1.0",
            "inputs": {"entities": "$objects"},
            "params": {"scope": "frame"},
        },
        {
            "id": "zone",
            "op": "region.manual@1.0",
            "inputs": {},
            "params": {
                "shape": "rectangle",
                "points": [[0.1, 0.1], [0.9, 0.9]],
            },
        },
        {
            "id": "reference",
            "op": "direction.manual@1.0",
            "inputs": {},
            "params": {
                "vector": [1.0, 0.0],
                "start": [0.2, 0.8],
                "end": [0.8, 0.8],
            },
        },
    ]
    variant["nodes"][draw_index:draw_index] = extra_nodes
    draw["inputs"].update(
        {
            "regions": "$zone",
            "directions": "$reference",
            "measurements": "$count",
        }
    )
    variant["outputs"].update(
        {
            "measurements": "$count",
            "regions": "$zone",
            "directions": "$reference",
        }
    )
    package = SkillPackage.model_validate(data)

    record = SkillPackageRuntime(
        build_default_registry(),
        rex=OneBoxRex(),
        run_store=RunStore(tmp_path / "runs"),
    ).run(package, package, media)

    result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
    assert result["measurements"][0]["value"] == 1
    assert result["regions"][0]["id"] == "zone"
    assert result["directions"][0]["key"] == "global"
    assert result["directions"][0]["metadata"]["start"] == [0.2, 0.8]
    assert {
        "measurements.json",
        "regions.json",
        "directions.json",
    } <= {path.name for path in record.run_dir.iterdir()}
    assert result["artifacts"]["measurements"].endswith("measurements.json")
    assert result["artifacts"]["regions"].endswith("regions.json")
    assert result["artifacts"]["directions"].endswith("directions.json")


def test_package_runtime_selects_video_variant_from_real_media(tmp_path):
    media = tmp_path / "input.avi"
    writer = cv2.VideoWriter(str(media), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 32))
    writer.write(np.zeros((32, 64, 3), dtype=np.uint8))
    writer.release()

    record = SkillPackageRuntime(
        build_default_registry(), rex=OneBoxRex(), run_store=RunStore(tmp_path / "runs")
    ).run(_package(), _package(), media)

    assert record.media_type == "video"
    assert record.variant == "video"
    assert record.annotated_media.suffix == ".mp4"
    result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
    assert result["media_policy"]["duration_seconds"] == pytest.approx(1.0)
    assert result["media_policy"]["sampled_frame_count"] == 1
    assert result["media_policy"]["rex_call_count"] == 1


def test_package_runtime_treats_empty_ui_end_seconds_as_unbounded(tmp_path):
    """A blank Gradio Number can arrive as 0.0, meaning no end limit."""
    media = tmp_path / "input.avi"
    writer = cv2.VideoWriter(
        str(media), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 32)
    )
    writer.write(np.zeros((32, 64, 3), dtype=np.uint8))
    writer.release()
    data = _package().model_dump(mode="json")
    sample = next(
        node
        for node in data["variants"]["video"]["nodes"]
        if node["id"] == "frames"
    )
    sample["params"]["end_seconds"] = 0.0
    package = SkillPackage.model_validate(data)

    record = SkillPackageRuntime(
        build_default_registry(), rex=OneBoxRex(), run_store=RunStore(tmp_path / "runs")
    ).run(package, package, media)

    result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
    assert record.annotated_media and record.annotated_media.suffix == ".mp4"
    assert result["media_policy"]["sampled_frame_count"] == 1
    assert result["media_policy"]["user_limited"] is False


def test_package_runtime_persists_warn_only_policy_without_truncating_video(tmp_path):
    media = tmp_path / "longer_than_demo_guidance.avi"
    writer = cv2.VideoWriter(
        str(media), cv2.VideoWriter_fourcc(*"MJPG"), 1.0, (64, 32)
    )
    for _ in range(3):
        writer.write(np.zeros((32, 64, 3), dtype=np.uint8))
    writer.release()
    data = _package().model_dump(mode="json")
    data["input"]["video_guidance"]["recommended_max_duration_seconds"] = 1.0
    package = SkillPackage.model_validate(data)
    rex = OneBoxRex()

    record = SkillPackageRuntime(
        build_default_registry(), rex=rex, run_store=RunStore(tmp_path / "runs")
    ).run(package, package, media)

    result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
    policy = result["media_policy"]
    assert policy["execution_allowed"] is True
    assert policy["recommended_limit_exceeded"] is True
    assert policy["user_limited"] is False
    assert policy["sampled_frame_count"] == 3
    assert rex.calls == 3
    assert "不会自动截断" in policy["warnings"][0]


def test_constraint_summary_links_semantic_atom_to_executed_trace(tmp_path):
    from core.semantic import SemanticNormalizer, WorkflowCompiler

    instruction = "检测穿着反光背心的人"
    semantic_ir = SemanticNormalizer().normalize_ledger(
        {
            "mode": "entity_query",
            "target": {
                "concept": "person",
                "source_span": "人",
                "phrases": ["person"],
            },
            "constraints": [
                {
                    "kind": "wearable",
                    "value": "reflective_vest",
                    "source": instruction,
                    "source_span": "穿着反光背心",
                    "phrases": ["wearing reflective vest"],
                }
            ],
            "logic": "all",
        },
        instruction,
    )
    package = WorkflowCompiler(build_default_registry()).compile(
        semantic_ir,
        original_instruction=instruction,
        requested_accept=["image"],
        skill_id="reflective_worker",
        display_name="穿反光背心人员",
    )
    media = tmp_path / "worker.jpg"
    Image.new("RGB", (80, 40), "white").save(media)

    record = SkillPackageRuntime(
        build_default_registry(), rex=OneBoxRex(), run_store=RunStore(tmp_path / "runs")
    ).run(package, package, media)

    result = json.loads((record.run_dir / "result.json").read_text("utf-8"))
    assert len(result["constraint_summary"]) == 1
    summary = result["constraint_summary"][0]
    assert summary["atom_id"] == "atom_1"
    assert summary["kind"] == "wearable"
    assert summary["source_span"] == "穿着反光背心"
    assert summary["polarity"] == "required"
    assert summary["bound_nodes"] == package.variants["image"].atom_bindings["atom_1"]
    assert {entry["node_id"] for entry in summary["trace"]} == set(
        summary["bound_nodes"]
    )
    assert all(entry["status"] == "success" for entry in summary["trace"])


def test_package_runtime_rejects_mismatched_file_before_calling_rex(tmp_path):
    media = tmp_path / "input.txt"
    media.write_text("not media", encoding="utf-8")
    rex = OneBoxRex()

    with pytest.raises(ValueError, match="unsupported media file"):
        SkillPackageRuntime(
            build_default_registry(), rex=rex, run_store=RunStore(tmp_path / "runs")
        ).run(_package(), _package(), media)

    assert rex.calls == 0
