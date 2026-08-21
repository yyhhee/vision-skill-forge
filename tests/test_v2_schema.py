from __future__ import annotations

import pytest
from pydantic import ValidationError

from core import schema


def _semantic_ir() -> dict:
    return {
        "schema_version": "1.0",
        "mode": "direct_grounding",
        "target": {
            "concept": "person",
            "source_span": "人",
            "phrases": ["person"],
        },
        "constraints": [],
        "logic": "all",
        "unresolved": [],
        "semantic_hash": "a" * 64,
    }


def _image_variant() -> dict:
    return {
        "media_type": "image",
        "status": "executable",
        "nodes": [
            {
                "id": "image",
                "op": "media.image@1.0",
                "inputs": {"media": "$input"},
                "params": {},
            }
        ],
        "outputs": {"frames": "$image"},
    }


def _video_variant() -> dict:
    return {
        "media_type": "video",
        "status": "executable",
        "nodes": [
            {
                "id": "video",
                "op": "media.video@1.0",
                "inputs": {"media": "$input"},
                "params": {},
            },
            {
                "id": "frames",
                "op": "video.sample@1.0",
                "inputs": {"video": "$video"},
                "params": {"mode": "fps", "fps": 2.0},
            },
        ],
        "outputs": {"frames": "$frames"},
    }


def _package_data() -> dict:
    return {
        "schema_version": "2.0",
        "skill_id": "person_detector",
        "version": 1,
        "display_name": "人员检测",
        "original_instruction": "检测人员",
        "compile_status": "compiled",
        "input": {
            "requested_accept": ["image", "video"],
            "accept": ["image", "video"],
            "video_guidance": {
                "recommended_max_duration_seconds": 30.0,
                "enforcement": "warn_only",
            },
        },
        "semantic_ir": _semantic_ir(),
        "variants": {
            "image": _image_variant(),
            "video": _video_variant(),
        },
        "compatibility_issues": [],
    }


def test_skill_package_supports_both_media_with_distinct_workflow_variants():
    assert hasattr(schema, "SkillPackage"), "V2 SkillPackage contract is missing"
    package = schema.SkillPackage.model_validate(_package_data())

    assert package.input.requested_accept == ["image", "video"]
    assert package.input.accept == ["image", "video"]
    assert package.select_variant("image").media_type == "image"
    assert package.select_variant("video").media_type == "video"


def test_skill_package_rejects_an_accepted_media_without_executable_variant():
    data = _package_data()
    del data["variants"]["video"]

    with pytest.raises(ValidationError, match="accepted media video requires an executable variant"):
        schema.SkillPackage.model_validate(data)


def test_skill_package_keeps_unsupported_request_out_of_actual_accept():
    data = _package_data()
    data["input"]["accept"] = ["video"]
    data["variants"]["image"] = {
        "media_type": "image",
        "status": "unsupported",
        "nodes": [],
        "outputs": {},
        "issue": "temporal semantics require video",
    }
    data["compatibility_issues"] = [
        {
            "media_type": "image",
            "code": "temporal_requires_video",
            "message": "时序语义需要视频",
        }
    ]

    package = schema.SkillPackage.model_validate(data)

    assert package.input.requested_accept == ["image", "video"]
    assert package.input.accept == ["video"]
    with pytest.raises(ValueError, match="image is not executable"):
        package.select_variant("image")


def test_skill_package_rejects_silent_media_downgrade_without_compatibility_issue():
    data = _package_data()
    data["input"]["accept"] = ["video"]
    del data["variants"]["image"]

    with pytest.raises(ValidationError, match="requested but unsupported media image requires a compatibility issue"):
        schema.SkillPackage.model_validate(data)


def test_workflow_variant_rejects_media_node_for_the_wrong_variant():
    data = _package_data()
    data["variants"]["image"] = _video_variant() | {"media_type": "image"}

    with pytest.raises(ValidationError, match="image variant must start from media.image"):
        schema.SkillPackage.model_validate(data)
