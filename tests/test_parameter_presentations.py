from __future__ import annotations

from core.parameter_presentations import parameter_presentation
import re

from core.registry import ParameterSpec, build_default_registry
from ui.event_rule_editor import display_value, friendly_choice_label


def test_common_technical_parameters_have_plain_business_explanations():
    iou = parameter_presentation("iou_threshold")
    gap = parameter_presentation("gap_tolerance_seconds")
    frames = parameter_presentation("max_missing_frames")

    assert iou.label == "同一目标匹配要求"
    assert "串错目标" in iou.detail
    assert gap.label == "允许短暂中断"
    assert gap.unit == "秒"
    assert frames.unit == "帧"


def test_unknown_parameter_still_has_safe_schema_derived_help():
    presentation = parameter_presentation(
        "custom_limit",
        ParameterSpec(kind="number", minimum=0, maximum=10),
        operator_help="控制当前统计上限。",
    )
    assert presentation.label
    assert "不小于 0" in presentation.detail
    assert presentation.level == "tuning"


def test_registered_atom_parameters_and_choices_use_business_language():
    registry = build_default_registry()
    technical_labels = []
    for definition in registry.definitions():
        for name, spec in definition.parameters.items():
            label = parameter_presentation(name, spec).label
            if re.search(r"[A-Za-z_]", label):
                technical_labels.append((definition.op, name, label))
    assert technical_labels == []
    assert friendly_choice_label("median") == "中位数"
    assert friendly_choice_label("sample_center") == "逐帧框中心归属"
    assert friendly_choice_label("pixels_per_second") == "像素/秒"
    assert display_value("frame_any") == "按同一画面汇总"
