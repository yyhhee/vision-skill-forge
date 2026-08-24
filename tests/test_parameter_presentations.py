from __future__ import annotations

from core.parameter_presentations import parameter_presentation
from core.registry import ParameterSpec


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
