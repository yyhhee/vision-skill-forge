from __future__ import annotations

from core.business_capabilities import build_business_capability_registry
from core.registry import build_default_registry


def test_business_capability_catalog_covers_all_user_facing_categories():
    operators = build_default_registry()
    catalog = build_business_capability_registry(operators)
    definitions = catalog.definitions()

    assert len(definitions) >= 20
    assert {
        "目标与属性",
        "空间与区域",
        "数量与测量",
        "轨迹与运动",
        "状态与事件",
        "时间与复杂编排",
        "逻辑组合",
        "输出与证据",
    } == {item.category for item in definitions}
    assert catalog.require("motion.wrong_way").media_requirements == ["video"]
    assert {
        "region",
        "direction",
    } == set(catalog.require("motion.wrong_way").resource_requirements)


def test_every_business_parameter_has_user_language_and_compiler_mapping_is_valid():
    operators = build_default_registry()
    catalog = build_business_capability_registry(operators)

    for capability in catalog.definitions():
        assert capability.display_name
        assert capability.description
        assert capability.compiler_recipe
        for atom in capability.atoms:
            assert operators.require(atom).op == atom
        for parameter in capability.parameters:
            assert parameter.label
            assert parameter.help
            assert "_" not in parameter.label


def test_business_capability_search_uses_business_terms_not_operator_ids():
    catalog = build_business_capability_registry(build_default_registry())
    assert catalog.search("红色")[0].capability_id == "attribute.color"
    assert any(item.capability_id == "motion.wrong_way" for item in catalog.search("逆行"))
    assert any(item.capability_id == "measure.count" for item in catalog.search("拥堵"))


def test_user_facing_capability_text_is_generic_while_ids_and_recipes_stay_stable():
    catalog = build_business_capability_registry(build_default_registry())

    color = catalog.require("attribute.color")
    missing = catalog.require("subject.missing_equipment")
    reverse = catalog.require("motion.wrong_way")
    assert color.display_name == "可见属性颜色"
    assert color.compiler_recipe == "visible_color"
    assert color.atoms == ["visual.color_fraction@1.0", "filter.apply@1.0"]
    assert missing.display_name == "主体缺少关联物"
    assert "安全帽" not in missing.description
    assert missing.compiler_recipe == "equipment_absence"
    assert reverse.display_name == "相对参考方向反向运动"
    assert "逆行只是交通场景" in reverse.description
    assert reverse.compiler_recipe == "reverse_motion"
