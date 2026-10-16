from __future__ import annotations

import json

from app_v2 import V2AppController, build_v2_app
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR, SkillPackage
from core.semantic import WorkflowCompiler


def _package():
    semantic = CanonicalSemanticIR.model_validate({
        "schema_version": "1.0",
        "mode": "direct_grounding",
        "target": {"concept": "person", "source_span": "人", "phrases": ["person"]},
        "constraints": [],
        "logic": "all",
        "unresolved": [],
        "semantic_hash": "d" * 64,
    })
    return WorkflowCompiler(build_default_registry()).compile(
        semantic,
        original_instruction="检测人",
        requested_accept=["image", "video"],
        skill_id="generic_editor",
        display_name="通用编辑",
    )


def _controller(tmp_path):
    return V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=None,
        rex=None,
    )


def test_generic_atomic_parameter_editor_reads_and_writes_effective_package(tmp_path):
    controller = _controller(tmp_path)
    effective = controller._dump(_package())
    choices, selected, parameters, _, rows = controller.atomic_parameter_controls(
        effective, "image variant"
    )

    assert choices and rows
    rex_node = next(
        row["node_id"] for row in rows
        if row["operator"] == "rex.ground@1.1" and row["parameter"] == "targets"
    )
    updated, status = controller.apply_atomic_parameter(
        effective,
        "image variant",
        rex_node,
        "targets",
        '[{"label":"车辆","phrases":["car"]}]',
    )
    package = SkillPackage.model_validate_json(updated)
    node = next(item for item in package.variants["image"].nodes if item.id == rex_node)
    assert node.params["targets"][0]["label"] == "车辆"
    assert status.startswith("✅")


def test_semantic_event_request_missing_event_output_is_visible_not_not_applicable(tmp_path):
    controller = _controller(tmp_path)
    data = _package().model_dump(mode="json")
    data["original_instruction"] = "识别视频中是否有人摔倒事件发生"
    data["semantic_ir"]["mode"] = "workflow"
    package = SkillPackage.model_validate(data)

    contract = controller.result_contract(controller._dump(package), "video")
    rendered = controller.format_result_sections(contract, {"events": []})

    assert contract["events"]["applicable"] is True
    assert contract["events"]["declared"] is False
    assert rendered["events"]["status"] == "适用 · 本次 0 条"
    assert rendered["events"]["diagnostics"][0]["code"] == "semantic_event_output_missing"


def test_ui_keeps_five_steps_adds_generic_atoms_and_hides_internal_region_id(tmp_path):
    config = build_v2_app(_controller(tmp_path)).get_config_file()
    dumped = json.dumps(config, ensure_ascii=False)
    assert "01 创建" in dumped and "05 资产" in dumped
    assert "事件规则编辑｜条件分支、时间编排、最终判定与业务输出" in dumped
    assert "复杂事件编排" in dumped
    assert "业务输出规格" in dumped
    assert "应用修改，更新运行版本" in dumped
    internal_id = next(
        component
        for component in config["components"]
        if component.get("props", {}).get("label") == "系统内部 ID"
    )
    assert internal_id["props"]["visible"] is False


def test_business_rule_editor_is_primary_and_atomic_graph_is_hidden(tmp_path):
    config = build_v2_app(_controller(tmp_path)).get_config_file()
    accordions = {
        component.get("props", {}).get("label", ""): component.get("props", {})
        for component in config["components"]
        if component["type"] == "accordion"
    }
    business = next(
        props for label, props in accordions.items()
        if label.startswith("事件规则编辑")
    )
    advanced = next(
        props for label, props in accordions.items()
        if label.startswith("高级原子编排")
    )
    assert business["open"] is True
    assert advanced["open"] is False
    assert advanced["visible"] is False
    compatibility = next(
        props for label, props in accordions.items()
        if label == "旧事件规则兼容区"
    )
    assert compatibility["visible"] is False


def test_empty_advanced_editor_dependencies_return_calm_empty_state(tmp_path):
    controller = _controller(tmp_path)
    parameter, value = controller.unified_node_parameters(
        "", "image variant", None
    )
    assert parameter["value"] is None
    assert value == ""
    assert controller.unified_parameter_value("", "image variant", "", "") == ""
