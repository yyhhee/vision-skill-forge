import importlib

import pytest


def load_api():
    try:
        schema = importlib.import_module("core.schema")
        registry = importlib.import_module("core.registry")
        validator = importlib.import_module("core.validator")
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"core skill API is not implemented: {exc}")
    return schema, registry, validator


def valid_image_skill():
    return {
        "version": "0.1",
        "name": "no_helmet",
        "display_name": "施工未戴安全帽",
        "original_instruction": "检测没有佩戴安全帽的人",
        "compile_status": "compiled",
        "input": {"accept": ["image"]},
        "nodes": [
            {
                "id": "frames",
                "op": "media.image@1.0",
                "inputs": {"media": "$input"},
                "params": {},
            },
            {
                "id": "resized",
                "op": "image.resize@1.0",
                "inputs": {"frames": "$frames"},
                "params": {"mode": "long_side", "long_side": 1280},
            },
            {
                "id": "people",
                "op": "rex.ground@1.0",
                "inputs": {"frames": "$resized"},
                "params": {
                    "targets": [
                        {
                            "label": "未戴安全帽人员",
                            "phrases": ["person not wearing a safety helmet"],
                        }
                    ]
                },
            },
            {
                "id": "drawn",
                "op": "output.draw@1.0",
                "inputs": {"frames": "$frames", "objects": "$people"},
                "params": {"show_labels": True},
            },
        ],
        "outputs": {"media": "$drawn"},
    }


def test_visual_skill_schema_rejects_unknown_fields():
    schema, _, _ = load_api()
    raw = valid_image_skill()
    raw["hidden_runtime_behavior"] = True

    with pytest.raises(schema.ValidationError):
        schema.VisualSkillSpec.model_validate(raw)


def test_registry_is_single_source_for_core_operator_contracts():
    _, registry_module, _ = load_api()
    registry = registry_module.build_default_registry()

    resize = registry.require("image.resize@1.0")
    assert resize.input_types == {"frames": "FrameSet"}
    assert resize.output_type == "FrameSet"
    assert resize.defaults == {
        "mode": "long_side",
        "long_side": 1280,
        "width": None,
        "height": None,
        "interpolation": "bilinear",
    }
    assert "保持比例" in resize.fixed_rule_text

    catalog = registry.planner_catalog()
    catalog_ops = {item["op"] for item in catalog}
    assert "rex.ground@1.0" in catalog_ops
    assert "temporal.persist@1.0" in catalog_ops


def test_validator_accepts_a_well_typed_image_pipeline():
    schema, registry_module, validator_module = load_api()
    spec = schema.VisualSkillSpec.model_validate(valid_image_skill())

    errors = validator_module.validate_skill(
        spec, registry_module.build_default_registry()
    )

    assert errors == []


@pytest.mark.parametrize(
    ("mutate", "expected_error"),
    [
        (
            lambda raw: raw["nodes"][1].update(op="image.unknown@1.0"),
            "unknown operator",
        ),
        (
            lambda raw: raw["nodes"][2]["inputs"].update(frames="$missing"),
            "unknown reference",
        ),
        (
            lambda raw: raw["nodes"][2]["inputs"].update(frames="$people"),
            "cycle",
        ),
        (
            lambda raw: raw["nodes"][2]["inputs"].update(frames="$input"),
            "type mismatch",
        ),
    ],
)
def test_validator_rejects_unexecutable_graphs(mutate, expected_error):
    schema, registry_module, validator_module = load_api()
    raw = valid_image_skill()
    mutate(raw)
    spec = schema.VisualSkillSpec.model_validate(raw)

    errors = validator_module.validate_skill(
        spec, registry_module.build_default_registry()
    )

    assert any(expected_error in error.lower() for error in errors), errors


def test_validator_requires_explicit_sampling_for_video_skills():
    schema, registry_module, validator_module = load_api()
    raw = valid_image_skill()
    raw["input"] = {"accept": ["video"]}
    spec = schema.VisualSkillSpec.model_validate(raw)

    errors = validator_module.validate_skill(
        spec, registry_module.build_default_registry()
    )

    assert any("video.sample@1.0" in error for error in errors)


def test_validator_rejects_out_of_range_manual_roi_coordinates():
    schema, registry_module, validator_module = load_api()
    spec = schema.VisualSkillSpec.model_validate(
        {
            "version": "0.1",
            "name": "manual_roi",
            "display_name": "手工区域",
            "original_instruction": "配置手工区域",
            "input": {"accept": ["image"]},
            "nodes": [
                {
                    "id": "roi",
                    "op": "region.manual@1.0",
                    "inputs": {},
                    "params": {"shape": "rectangle", "points": [[-0.1, 0.2], [0.9, 1.2]]},
                }
            ],
            "outputs": {"region": "$roi"},
        }
    )
    errors = validator_module.validate_skill(spec, registry_module.build_default_registry())
    assert any("invalid type for parameter points" in error for error in errors)


def test_validator_allows_object_crop_region_to_extend_beyond_subject_box():
    schema, registry_module, validator_module = load_api()
    raw = valid_image_skill()
    raw["nodes"].insert(-1, {
        "id": "extended_crop",
        "op": "object.crop@1.0",
        "inputs": {"frames": "$resized", "objects": "$people"},
        "params": {
            "padding_fraction": 0.0,
            "subject_region": [-0.6, -0.6, 1.6, 1.2],
        },
    })
    raw["outputs"]["crops"] = "$extended_crop"
    spec = schema.VisualSkillSpec.model_validate(raw)

    errors = validator_module.validate_skill(
        spec, registry_module.build_default_registry()
    )

    assert not any("subject_region" in error for error in errors)


def test_validator_rejects_invalid_fixed_tracking_and_temporal_parameters():
    import json
    from pathlib import Path

    schema, registry_module, validator_module = load_api()
    root = Path(__file__).resolve().parents[1]
    raw = json.loads(next((root / "presets").glob("P05*.json")).read_text("utf-8"))
    next(node for node in raw["nodes"] if node["op"] == "track.iou@1.0")["params"]["iou_threshold"] = 1.5
    next(node for node in raw["nodes"] if node["op"] == "temporal.persist@1.0")["params"]["scope"] = "camera"
    spec = schema.VisualSkillSpec.model_validate(raw)
    errors = validator_module.validate_skill(spec, registry_module.build_default_registry())
    assert any("iou_threshold above maximum" in error for error in errors)
    assert any("invalid value for parameter scope" in error for error in errors)


def test_validator_rejects_single_input_boolean_combiner():
    schema, registry_module, validator_module = load_api()
    raw = valid_image_skill()
    raw["nodes"].insert(-1, {
        "id": "is_related",
        "op": "spatial.associate@1.0",
        "inputs": {"subjects": "$people", "objects": "$people"},
        "params": {"relation": "overlap", "threshold": 0.5},
    })
    raw["nodes"].insert(-1, {
        "id": "fake_all",
        "op": "logic.all@1.0",
        "inputs": {"conditions": "$is_related"},
        "params": {},
    })
    raw["nodes"][-1]["inputs"]["objects"] = "$people"
    raw["outputs"]["condition"] = "$fake_all"
    spec = schema.VisualSkillSpec.model_validate(raw)

    errors = validator_module.validate_skill(spec, registry_module.build_default_registry())

    assert any("requires at least two condition references" in error for error in errors), errors


def test_validator_rejects_enabled_branch_that_cannot_reach_any_output():
    schema, registry_module, validator_module = load_api()
    raw = valid_image_skill()
    raw["nodes"].insert(-1, {
        "id": "unused_posture",
        "op": "rex.ground@1.0",
        "inputs": {"frames": "$resized"},
        "params": {"targets": [{"label": "蹲姿", "phrases": ["squatting person"]}]},
    })
    spec = schema.VisualSkillSpec.model_validate(raw)

    errors = validator_module.validate_skill(spec, registry_module.build_default_registry())

    assert any("cannot reach any declared output" in error for error in errors), errors
