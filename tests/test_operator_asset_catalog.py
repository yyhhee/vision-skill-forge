from __future__ import annotations

from pathlib import Path

from core.editor_generation import build_editor_document
from core.operator_asset_catalog import build_operator_asset_catalog
from core.registry import build_default_registry
from core.schema import SkillPackage


def test_operator_assets_match_runtime_registry_and_every_parameter_has_help():
    registry = build_default_registry()
    assets = build_operator_asset_catalog(registry)

    assert len(assets) == len(registry.definitions())
    assert {item["operator"] for item in assets} == {
        item.op for item in registry.definitions()
    }
    assert {item["layer"] for item in assets} == {"业务组合", "系统基础"}
    assert all(item["layer_description"] for item in assets)
    assert all(
        item["default_visible"] == (item["layer"] == "业务组合")
        for item in assets
    )
    assert next(item for item in assets if item["operator"] == "rex.ground@1.1")[
        "layer"
    ] == "业务组合"
    for asset in assets:
        assert asset["category"]
        assert asset["description"]
        for parameter in asset["parameters"]:
            assert parameter["label"]
            assert parameter["short_help"]
            assert parameter["detail"]
            assert parameter["developer_info"]["technical_name"]


def test_operator_assets_can_trace_current_skill_usage_back_to_branch():
    package = SkillPackage.model_validate_json(
        next(Path("presets_v2").glob("P05*.json")).read_text("utf-8")
    )
    document = build_editor_document(package, source_type="preset")
    assets = build_operator_asset_catalog(build_default_registry(), document)
    used = [item for item in assets if item["current_usage"]]

    assert used
    assert any(
        usage["node_id"] and usage["media_type"] == "video"
        for item in used
        for usage in item["current_usage"]
    )
