from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .registry import ParameterSpec


@dataclass(frozen=True)
class ParameterPresentation:
    label: str
    short_help: str
    detail: str
    unit: str | None = None
    recommended: str | None = None
    larger_effect: str | None = None
    smaller_effect: str | None = None
    example: str | None = None
    level: str = "business"
    value_transform: str | None = None

    def to_dict(self, *, technical_name: str | None = None) -> dict[str, Any]:
        result = asdict(self)
        if technical_name is not None:
            result["developer_info"] = {"technical_name": technical_name}
        return result


_PRESENTATIONS: dict[str, ParameterPresentation] = {
    "iou_threshold": ParameterPresentation(
        "同一目标匹配要求",
        "相邻帧目标框重叠达到该比例时，才认为是同一目标。",
        "用于保持目标轨迹连续。调低更容易接续轨迹但可能串错目标；调高更严格但轨迹更容易中断。",
        "%",
        "30%–60%",
        "匹配更严格，串轨更少，但轨迹可能中断。",
        "更容易保持连续轨迹，但相邻目标可能被串联。",
        "两帧车辆框重叠 45%，设置 40% 时可接续为同一车辆。",
        value_transform="percent_to_ratio",
    ),
    "overlap_threshold": ParameterPresentation(
        "目标进入区域的最低比例",
        "目标框与区域重叠达到该比例时，才判断目标在区域内。",
        "调高要求目标更深入区域；调低会在区域边缘更早命中。",
        "%",
        "30%–60%",
        "区域归属更严格。",
        "边缘目标更容易计入。",
        value_transform="percent_to_ratio",
    ),
    "gap_tolerance_seconds": ParameterPresentation(
        "允许短暂中断",
        "条件短暂消失不超过该时间时，仍视为连续满足。",
        "用于容忍遮挡或偶发漏检。调大可能把两段独立事件连接；调小会更严格分段。",
        "秒",
        "0.3–1.0秒",
        "更能容忍漏检，但可能连接两次事件。",
        "分段更严格，但单次漏检可能中断事件。",
        "持续5秒且允许中断0.5秒时，中间漏检0.3秒仍算连续。",
    ),
    "allowed_gap_seconds": ParameterPresentation(
        "允许短暂中断",
        "阶段命中短暂消失时允许保留连续状态的时间。",
        "用于复杂事件阶段的连续判定，影响与“允许短暂中断”相同。",
        "秒",
        "0.3–1.0秒",
    ),
    "min_displacement_pixels": ParameterPresentation(
        "判定已移动的最小距离",
        "位移不足时不计算运动方向，减少静止框抖动误判。",
        "调大可减少抖动误判但可能漏掉慢速移动；调小响应更灵敏。",
        "%画面对角线",
        "1%–3%",
        "更稳定但可能漏掉小位移。",
        "更灵敏但更容易受框抖动影响。",
        value_transform="screen_diagonal_percent",
    ),
    "max_missing_frames": ParameterPresentation(
        "目标暂时消失可保留多少帧",
        "目标漏检后继续保留轨迹身份的最大帧数。",
        "调大可跨越更多漏检帧但增加串轨风险；帧数保持帧单位。",
        "帧",
        "2–10帧",
        "更能跨越遮挡，但可能串轨。",
        "身份更严格，但轨迹容易中断。",
    ),
    "window_frames": ParameterPresentation(
        "运动观察帧数",
        "使用最近多少帧计算方向或速度。",
        "帧数少响应快但容易抖动；帧数多更稳定但判定更慢。",
        "帧",
        "3–10帧",
        "结果更稳定但响应更慢。",
        "响应更快但方向可能抖动。",
    ),
    "required_ratio": ParameterPresentation(
        "时间窗口内至少满足",
        "统计窗口内条件成立时间所需占比。",
        "比例越高越接近持续满足；比例越低越能容忍间歇命中。",
        "%",
        "70%–100%",
        "条件更严格。",
        "更能容忍间歇命中。",
        value_transform="percent_to_ratio",
    ),
    "correlation_scope": ParameterPresentation(
        "多个事件按什么对象关联",
        "决定复杂事件是否必须发生在同一目标、轨迹、目标对或区域。",
        "选择错误可能把不同对象的事件错误组合。本期只开放全局、同一目标、同一轨迹、同一目标对和同一区域。",
        recommended="按业务主体选择",
    ),
    "maximum_matches": ParameterPresentation(
        "最多保留的事件组合",
        "限制复杂组合结果数量，避免大量重复实例。",
        "调大保留更多组合但结果与资源消耗增加；调小可能丢弃次要组合。",
        "个",
        "10–100个",
        "保留更多组合。",
        "更快更简洁，但可能截断结果。",
    ),
    "duration_seconds": ParameterPresentation(
        "持续时间",
        "条件连续或累计达到该时长后才成立。",
        "时长越大越能过滤短暂误报，但告警更慢；设为0表示立即判断。",
        "秒",
    ),
    "minimum_seconds": ParameterPresentation(
        "至少持续",
        "条件达到该时长后才认为阶段完成。",
        "调大更严格且更慢；调小响应更快但更容易接受瞬时命中。",
        "秒",
    ),
    "window_seconds": ParameterPresentation(
        "完成时间窗口",
        "相关阶段必须在该媒体时间窗口内完成。",
        "窗口越大越容易组合相隔较远的事件；越小要求事件更紧密。",
        "秒",
    ),
    "threshold": ParameterPresentation(
        "判定阈值",
        "实际值与该阈值比较后得到是否满足。",
        "具体调大/调小影响由当前比较方式决定。",
    ),
    "value": ParameterPresentation(
        "比较值",
        "与实际数量或测量值进行比较的目标值。",
        "结合大于、至少、等于、小于等比较方式使用。",
    ),
    "operator": ParameterPresentation(
        "比较方式",
        "选择大于、至少、等于、不超过或小于。",
        "比较方式与阈值共同决定条件是否成立。",
    ),
    "label": ParameterPresentation(
        "业务名称",
        "用户在结果和事件记录中看到的名称。",
        "业务名称不改变原模型标签；框标签由结果标签策略独立配置。",
    ),
    "output_label": ParameterPresentation(
        "结果标签",
        "该能力输出在业务结果中使用的名称。",
        "保留原模型标签时，业务标签与模型标签会分别保存。",
    ),
    "phrases": ParameterPresentation(
        "检测描述",
        "发送给视觉模型的目标或可见属性描述。",
        "使用可直接从画面观察的短语，不写规则结论或坐标输出协议。",
    ),
    "targets": ParameterPresentation(
        "目标类别",
        "选择需要识别的一个或多个目标类别。",
        "多类别可合并输出，也可以后续按类别分别统计。",
    ),
    "regions": ParameterPresentation(
        "判断区域",
        "选择 02 已标注的一个或多个真实区域。",
        "区域数量无需预先确定，保存标注后候选项自动刷新。",
    ),
    "points": ParameterPresentation(
        "区域形状",
        "由 02 标注提供的矩形或多边形坐标。",
        "普通用户应在 02 画区域，不直接编辑坐标数组。",
        level="resource",
    ),
    "vector": ParameterPresentation(
        "参考方向",
        "由 02 标注提供的方向箭头。",
        "用于同向、逆向或方向偏差判断。",
        level="resource",
    ),
    "fps": ParameterPresentation(
        "目标抽帧率",
        "视频每秒选取多少帧进行分析。",
        "提高会增加时间精度和调用量；降低会更快但可能错过短事件。",
        "帧/秒",
        level="tuning",
    ),
    "frame_step": ParameterPresentation(
        "每隔多少帧分析一次",
        "按原视频帧序号固定间隔抽帧。",
        "数值越大调用越少，但时间粒度更粗；保持帧单位。",
        "帧",
        level="tuning",
    ),
}


_TOKEN_LABELS = {
    "after": "之后",
    "before": "之前",
    "seconds": "秒数",
    "count": "数量",
    "minimum": "最小",
    "maximum": "最大",
    "mode": "方式",
    "scope": "范围",
    "label": "名称",
    "labels": "类别",
    "direction": "方向",
    "directions": "方向集合",
    "region": "区域",
    "regions": "区域集合",
    "window": "窗口",
    "time": "时间",
    "start": "开始",
    "end": "结束",
    "width": "宽度",
    "height": "高度",
    "ratio": "比例",
    "threshold": "阈值",
    "metric": "度量方式",
    "selection": "选择",
    "severity": "告警级别",
    "enabled": "是否启用",
    "frames": "帧数",
    "hits": "命中次数",
    "state": "状态",
    "from": "起始",
    "to": "目标",
    "same": "同一",
    "operator": "比较方式",
}


def _fallback_label(name: str) -> str:
    tokens = name.split("_")
    translated = [_TOKEN_LABELS.get(token, token) for token in tokens]
    return " ".join(translated)


def parameter_presentation(
    name: str,
    spec: ParameterSpec | None = None,
    *,
    operator_help: str = "",
) -> ParameterPresentation:
    if name in _PRESENTATIONS:
        return _PRESENTATIONS[name]
    range_text = ""
    if spec is not None:
        parts = []
        if spec.minimum is not None:
            parts.append(f"不小于 {spec.minimum}")
        if spec.maximum is not None:
            parts.append(f"不大于 {spec.maximum}")
        if spec.choices:
            parts.append("可选：" + "、".join(map(str, spec.choices)))
        range_text = "；".join(parts)
    detail = operator_help or "该参数用于控制当前能力的业务判断。"
    if range_text:
        detail = f"{detail} 合法范围：{range_text}。"
    return ParameterPresentation(
        label=_fallback_label(name),
        short_help=f"设置“{_fallback_label(name)}”在当前能力中的取值。",
        detail=detail,
        level="tuning",
    )


__all__ = ["ParameterPresentation", "parameter_presentation"]
