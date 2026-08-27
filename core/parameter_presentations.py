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
    "min_displacement_box_ratio": ParameterPresentation(
        "远处小目标位移灵敏度",
        "按目标框尺寸降低远处小目标的方向位移门槛。",
        "数值越小越容易识别远处小目标的运动方向，但过小可能把检测框抖动当成移动；0 表示只使用固定距离。",
        "%目标框对角线",
        "15%–30%",
        "要求移动更明显，抖动误判更少。",
        "更容易识别远处慢速小目标，但需留意框抖动。",
        value_transform="percent_to_ratio",
    ),
    "motion_prediction": ParameterPresentation(
        "使用运动预测接续轨迹",
        "同时比较当前位置和预测位置，选择更符合运动趋势的同一目标。",
        "适合透视变化大、移动较快或采样间隔较大的视频。开启后可减少轨迹断裂；密集交叉场景仍应配合运动方向一致性。",
        recommended="高速公路、远距离运动目标建议开启",
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
    "keep": ParameterPresentation(
        "重复框保留策略",
        "多个检测框被判断为同一目标后，选择保留哪个框。",
        "普通场景可按输入顺序保留；切片小目标场景建议选择“优先保留定位更准的框”，系统会优先使用未被切片边界截断的高分辨率结果。",
        recommended="切片检测使用“优先保留定位更准的框”",
    ),
    "aspect_ratio_threshold": ParameterPresentation(
        "目标框最小宽高比",
        "目标框实际像素宽度与高度的比例达到该值时，才保留横向目标。",
        "可用于过滤把车灯、车尾局部误认为整车的异常窄框。数值调高过滤更严格，也可能漏掉严重遮挡或特殊视角目标。",
        recommended="车辆正面或侧面通常可从 0.6 开始调整",
        larger_effect="异常窄框更少，但遮挡目标可能被过滤。",
        smaller_effect="保留更多目标，但局部误框可能增加。",
    ),
    "show_labels": ParameterPresentation(
        "框上显示类别名称",
        "控制是否在每个目标框旁显示人员、车辆等类别文字。",
        "密集场景关闭后框线更清楚，目标类别仍保存在结果明细中。",
    ),
    "show_event_labels": ParameterPresentation(
        "框上显示事件名称",
        "控制是否只在触发事件的目标框旁显示逆行、摔倒等业务事件名称。",
        "可关闭普通类别名称、保留事件名称，避免密集场景文字遮挡目标。",
    ),
    "show_track_id": ParameterPresentation(
        "框上显示轨迹编号",
        "控制是否在视频目标框旁显示 track_1 等轨迹身份。",
        "排查轨迹串联时可开启；密集场景建议关闭以减少文字遮挡。",
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
    "membership_mode": ParameterPresentation(
        "区域归属方式",
        "选择目标或轨迹按什么方式归入标注区域。",
        "框中心适合互不重叠的区域；逐帧中心响应更及时；轨迹多数中心更稳定。",
    ),
    "overlap_threshold": ParameterPresentation(
        "目标与区域最低重叠比例",
        "区域归属方式选择“按框重叠”时，目标框至少有多少比例落入区域才保留。",
        "0 到 1；例如 0.2 表示目标框至少 20% 位于任一标注区域内。",
    ),
    "keep": ParameterPresentation(
        "保留区域内或区域外目标",
        "选择保留标注区域内目标，或反向保留区域外目标。",
        "业务检测通常选择区域内；排除区场景可选择区域外。",
    ),
    "aggregation": ParameterPresentation(
        "统计汇总方式",
        "选择使用平均值、中位数或按目标分别保留结果。",
        "中位数更不易受极端值影响，平均值会反映所有样本。",
    ),
    "unit": ParameterPresentation(
        "测量单位",
        "选择当前数值采用的单位。",
        "单位必须与阈值含义一致；当前像素速度按媒体时间计算。",
    ),
    "same_label_only": ParameterPresentation(
        "只关联同类别目标",
        "开启后，不会把不同检测类别的框接成同一条轨迹。",
        "通常建议开启；多类别本来表示同一业务目标时才考虑关闭。",
    ),
    "motion_consistency": ParameterPresentation(
        "防止轨迹突然反向串车",
        "开启后，已形成运动趋势的轨迹不会突然关联到反方向移动的相邻目标。",
        "密集交通和方向判断建议开启；普通目标检测可关闭。",
    ),
    "min_direction_cosine": ParameterPresentation(
        "轨迹转向连续性",
        "限制同一轨迹相邻两段运动方向允许变化的程度。",
        "0 表示不允许突然超过 90° 转向；越接近 1 越严格。",
    ),
    "min_motion_pixels": ParameterPresentation(
        "启用转向检查的最小位移",
        "位移达到该像素数后才检查轨迹是否突然反向，避免把静止抖动当作转向。",
        "数值过小容易受检测框抖动影响。",
        "像素",
    ),
    "combine_scope": ParameterPresentation(
        "条件如何对齐",
        "选择按同一对象或区域逐项组合，还是按同一画面时刻汇总组合。",
        "按对象或区域组合要求条件 key 一致；跨区域条件通常需要按画面时刻汇总。",
    ),
    "scope": ParameterPresentation(
        "持续判定对象",
        "选择持续时间按全局、同一区域、同一目标或同一轨迹分别计算。",
        "区域规则通常选择同一区域，目标行为通常选择同一轨迹。",
    ),
    "trigger_mode": ParameterPresentation(
        "满足后如何触发",
        "选择首次满足时触发一次，或条件再次达到要求时重复触发。",
        "重复触发会产生更多事件记录，应配合冷却或中断设置使用。",
    ),
    "subject_region": ParameterPresentation(
        "目标内部判断范围",
        "限定只在目标框内部的某一部分查找属性或关联对象。",
        "该范围由业务模板或专用配置生成；普通用户只需确认，上下左右比例不会作为原始数组开放编辑。",
        level="resource",
    ),
    "overrides": ParameterPresentation(
        "各区域阈值",
        "保存每个已标注区域各自生效的比较值。",
        "请在“每个标注区域分别配置”中修改，系统自动维护区域与数值的对应关系。",
        level="resource",
    ),
    "operator_overrides": ParameterPresentation(
        "各区域比较方式",
        "保存每个已标注区域各自生效的大于、至少、等于或小于关系。",
        "请在“每个标注区域分别配置”中修改，不直接编辑内部映射。",
        level="resource",
    ),
    "scope_overrides": ParameterPresentation(
        "各标注区域的独立参数",
        "保存不同区域分别设置的阈值、方向关系、持续时间或容错时间。",
        "请在“每个标注区域分别配置”中修改，系统自动维护区域和原子参数的对应关系；这里仅展示生效摘要。",
    ),
    "override_scope_field": ParameterPresentation(
        "区域身份来源",
        "指定上游结果中用于识别标注区域的字段。",
        "这是系统连接条件与区域持续策略的内部约定，通常无需修改。",
        level="resource",
    ),
    "state_labels": ParameterPresentation(
        "状态名称对应关系",
        "说明模型状态与业务状态名称如何对应。",
        "由状态条件卡片或技能模板维护，避免直接修改内部映射造成状态含义不一致。",
        level="resource",
    ),
    "transitions": ParameterPresentation(
        "允许的状态变化",
        "定义哪些起始状态到目标状态的变化可形成事件。",
        "由状态转变卡片维护；此处只展示当前已编译规则。",
        level="resource",
    ),
    "correlation_fields": ParameterPresentation(
        "事件关联字段",
        "指定复杂事件阶段按哪些业务身份或区域字段关联。",
        "由复杂事件编排维护，避免直接编辑字段数组。",
        level="resource",
    ),
    "large_min_area": ParameterPresentation(
        "大目标最小面积比例",
        "面积达到该比例后按大目标处理。",
        "与小目标最大面积比例一起决定分层检测或筛选边界。",
        "%画面面积",
        value_transform="percent_to_ratio",
    ),
    "small_max_area": ParameterPresentation(
        "小目标最大面积比例",
        "面积不超过该比例时按小目标处理。",
        "调大可让更多目标进入小目标增强流程，但会增加处理量。",
        "%画面面积",
        value_transform="percent_to_ratio",
    ),
    "max_frames": ParameterPresentation(
        "最多分析帧数",
        "限制单次运行最多处理多少帧。",
        "为空表示不额外限制；调小运行更快，但可能截断后续事件。",
        "帧",
    ),
    "max_gap_seconds": ParameterPresentation(
        "阶段最大间隔",
        "前后阶段相隔超过该时间时不再组成同一复杂事件。",
        "调大允许事件相隔更久，调小要求阶段更紧密。",
        "秒",
    ),
    "max_seconds": ParameterPresentation(
        "最长持续时间",
        "限制单个事件或阶段可持续的最长时间。",
        "用于避免无限延长事件；应大于业务要求的最短持续时间。",
        "秒",
    ),
    "min_fraction": ParameterPresentation(
        "最低占比",
        "实际占比达到该值后条件才成立。",
        "调高更严格，调低可提高召回但可能增加误判。",
        "%",
        value_transform="percent_to_ratio",
    ),
    "color_tolerance": ParameterPresentation(
        "颜色边界判定",
        "选择严格像素颜色，或在模型已定位属性证据时允许相邻色边界。",
        "严格模式适合仅靠图像像素筛选；语义容差仅用于模型已确认的属性证据，例如把姜黄、金黄衣物作为黄色的边界情况复核。",
        recommended="普通用户保持系统自动选择",
        level="tuning",
    ),
    "min_hits": ParameterPresentation(
        "确认轨迹至少命中帧数",
        "目标连续命中达到该帧数后才确认轨迹。",
        "调大可过滤偶发框但确认更慢；调小响应快但短暂误检可能形成轨迹。",
        "帧",
    ),
    "min_span_seconds": ParameterPresentation(
        "最短时间跨度",
        "首尾命中至少跨越该时长后才成立。",
        "用于区分瞬时重复命中和真实持续过程。",
        "秒",
    ),
    "output_fps": ParameterPresentation(
        "结果视频帧率",
        "设置输出结果视频每秒显示多少帧。",
        "只影响结果媒体播放；不会改变实际分析帧率。",
        "帧/秒",
    ),
    "output_fps_mode": ParameterPresentation(
        "结果视频帧率来源",
        "选择跟随源视频、分析时间线或使用固定帧率。",
        "该设置只控制结果媒体，不改变事件判定。",
    ),
    "overlap_x": ParameterPresentation(
        "切片横向重叠比例",
        "相邻切片在水平方向保留多少重叠。",
        "调大可减少边缘目标被切断，但会增加模型调用量和重复框。",
        "%",
        value_transform="percent_to_ratio",
    ),
    "overlap_y": ParameterPresentation(
        "切片纵向重叠比例",
        "相邻切片在垂直方向保留多少重叠。",
        "调大可减少边缘目标被切断，但会增加模型调用量和重复框。",
        "%",
        value_transform="percent_to_ratio",
    ),
    "same_source_only": ParameterPresentation(
        "只关联同一来源",
        "开启后只允许来自同一媒体来源的对象或事件互相关联。",
        "单媒体运行建议开启；跨来源关联应由更高层编排负责。",
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
    "aspect": "宽高",
    "color": "颜色",
    "consume": "完成后清除",
    "events": "事件",
    "event": "事件",
    "source": "来源",
    "cooldown": "冷却",
    "correlation": "关联",
    "fields": "字段",
    "deduplicate": "去重",
    "iou": "交并比",
    "ios": "交叠比例",
    "default": "默认",
    "dimension": "判断维度",
    "dominance": "主导",
    "margin": "容差",
    "evidence": "证据",
    "field": "字段",
    "group": "分组",
    "by": "依据",
    "history": "历史",
    "include": "包含",
    "full": "完整",
    "frame": "画面",
    "interpolation": "缩放插值",
    "interval": "间隔",
    "keep": "保留",
    "key": "对象键",
    "filter": "筛选",
    "large": "大目标",
    "small": "小目标",
    "area": "面积",
    "long": "长边",
    "side": "边长",
    "gap": "间断",
    "span": "跨度",
    "tracks": "轨迹数",
    "notification": "通知",
    "output": "输出",
    "overlap": "重叠",
    "overrides": "分区域配置",
    "padding": "外扩",
    "fraction": "比例",
    "position": "位置",
    "positive": "成立",
    "query": "查询",
    "prompt": "提示词",
    "relation": "空间关系",
    "repeat": "重复",
    "policy": "策略",
    "required": "要求",
    "selection": "选择",
    "severity": "告警级别",
    "shape": "形状",
    "show": "显示",
    "measurements": "测量结果",
    "track": "轨迹",
    "id": "编号",
    "trajectory": "轨迹线",
    "size": "尺寸",
    "statistic": "统计方式",
    "steps": "阶段",
    "subject": "主体",
    "tile": "切片",
    "transitions": "状态变化",
    "identity": "身份",
    "phrase": "检测描述",
    "ratio": "比例",
    "enabled": "启用",
    "absolute": "绝对",
    "relative": "相对",
    "empty": "空",
    "regions": "区域集合",
    "object": "对象",
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
