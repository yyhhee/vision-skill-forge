from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .visual_catalog import COLOR_NAMES


@dataclass(frozen=True)
class ParameterSpec:
    kind: str
    required: bool = False
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class OperatorDefinition:
    op: str
    display_name: str
    execution_scope: str
    input_types: dict[str, str]
    output_type: str
    defaults: dict[str, Any]
    fixed_rule_text: str
    parameters: dict[str, ParameterSpec] = field(default_factory=dict)
    optional_inputs: frozenset[str] = frozenset()

    def planner_entry(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "display_name": self.display_name,
            "scope": self.execution_scope,
            "inputs": self.input_types,
            "optional_inputs": sorted(self.optional_inputs),
            "output": self.output_type,
            "defaults": self.defaults,
            "parameters": {
                name: {
                    "kind": spec.kind,
                    "required": spec.required,
                    "choices": list(spec.choices),
                    "minimum": spec.minimum,
                    "maximum": spec.maximum,
                }
                for name, spec in self.parameters.items()
            },
            "rule": self.fixed_rule_text,
        }


class OperatorRegistry:
    def __init__(self, definitions: list[OperatorDefinition]):
        self._definitions: dict[str, OperatorDefinition] = {}
        for definition in definitions:
            if definition.op in self._definitions:
                raise ValueError(f"duplicate operator: {definition.op}")
            self._definitions[definition.op] = definition

    def get(self, op: str) -> OperatorDefinition | None:
        return self._definitions.get(op)

    def require(self, op: str) -> OperatorDefinition:
        definition = self.get(op)
        if definition is None:
            raise KeyError(f"unknown operator: {op}")
        return definition

    def planner_catalog(self) -> list[dict[str, Any]]:
        return [
            self._definitions[op].planner_entry()
            for op in sorted(self._definitions)
        ]

    def definitions(self) -> list[OperatorDefinition]:
        """Return the stable public operator catalog used by the V3 editor."""

        return [self._definitions[op] for op in sorted(self._definitions)]

    def __contains__(self, op: str) -> bool:
        return op in self._definitions


def _p(
    kind: str,
    *,
    required: bool = False,
    choices: tuple[Any, ...] = (),
    minimum: float | None = None,
    maximum: float | None = None,
) -> ParameterSpec:
    return ParameterSpec(kind, required, choices, minimum, maximum)


def build_default_registry() -> OperatorRegistry:
    definitions = [
        OperatorDefinition(
            "media.image@1.0",
            "图片输入",
            "media",
            {"media": "Media"},
            "FrameSet",
            {},
            "将一张图片转换为包含一个原始坐标帧的 FrameSet。",
        ),
        OperatorDefinition(
            "media.video@1.0",
            "视频输入",
            "media",
            {"media": "Media"},
            "Video",
            {},
            "读取视频元数据，不进行隐式抽帧。",
        ),
        OperatorDefinition(
            "video.sample@1.1",
            "视频抽帧",
            "media",
            {"video": "Video"},
            "FrameSet",
            {
                "mode": "fps",
                "fps": 1.0,
                "interval_seconds": 1.0,
                "frame_step": 1,
                "start_seconds": 0.0,
                "end_seconds": None,
                "max_frames": None,
            },
            "按显式 fps、时间间隔或帧步长抽帧；保留原帧号、时间戳，且不实施隐藏时长截断。",
            {
                "mode": _p("string", choices=("fps", "interval", "frame_step")),
                "fps": _p("number", minimum=0.01),
                "interval_seconds": _p("number", minimum=0.001),
                "frame_step": _p("integer", minimum=1),
                "start_seconds": _p("number", minimum=0),
                "end_seconds": _p("number_or_null", minimum=0),
                "max_frames": _p("integer_or_null", minimum=1),
            },
        ),
        OperatorDefinition(
            "image.resize@1.1",
            "图像缩放",
            "frame",
            {"frames": "FrameSet"},
            "FrameSet",
            {"mode": "long_side", "long_side": 1280, "width": None, "height": None, "interpolation": "bilinear"},
            "保持比例、contain padding 或拉伸；每一步写入可逆 TransformChain 并回映到原媒体归一化坐标。",
            {
                "mode": _p("string", choices=("identity", "long_side", "contain", "stretch")),
                "long_side": _p("integer_or_null", minimum=1),
                "width": _p("integer_or_null", minimum=1),
                "height": _p("integer_or_null", minimum=1),
                "interpolation": _p("string", choices=("nearest", "bilinear", "bicubic")),
            },
        ),
        OperatorDefinition(
            "image.tile@1.1",
            "图像切片",
            "frame",
            {"frames": "FrameSet"},
            "FrameSet",
            {"tile_width": 1024, "tile_height": 1024, "overlap_x": 0.2, "overlap_y": 0.2, "include_full_frame": True},
            "按独立 x/y 重叠率切片，可同时保留全图；来源顺序固定为 full-frame 后 tiles，坐标经 TransformChain 回映。",
            {
                "tile_width": _p("integer", minimum=1),
                "tile_height": _p("integer", minimum=1),
                "overlap_x": _p("number", minimum=0.0, maximum=0.9),
                "overlap_y": _p("number", minimum=0.0, maximum=0.9),
                "include_full_frame": _p("boolean"),
            },
        ),
        OperatorDefinition(
            "object.crop@1.0",
            "按实体裁剪",
            "frame",
            {"frames": "FrameSet", "objects": "EntitySet"},
            "FrameSet",
            {
                "padding_fraction": 0.0,
                "subject_region": [0.0, 0.0, 1.0, 1.0],
            },
            "按实体原图坐标和归一化子区域裁剪，追加可逆 TransformChain，并保留来源实体 ID。",
            {
                "padding_fraction": _p("number", minimum=0.0, maximum=1.0),
                "subject_region": _p("relative_box"),
            },
        ),
        OperatorDefinition(
            "rex.ground@1.1",
            "Rex 原始自然语言检测",
            "frame",
            {"frames": "FrameSet"},
            "ObjectSet",
            {"targets": []},
            "将显式肯定式 phrase 发送给 Rex 并回映标签与原图坐标；计数型新技能可每个目标只发送一个主短语，以避免同义短语重复候选。本节点不做隐藏去重。",
            {
                "targets": _p("target_list", required=True),
                "query_prompt": _p("string"),
                "phrase_selection": _p(
                    "string", choices=("all_phrases", "primary_per_target")
                ),
            },
        ),
        OperatorDefinition(
            "objects.deduplicate@1.0",
            "同标签确定性去重",
            "frame",
            {"objects": "EntitySet"},
            "ObjectSet",
            {"metric": "ios", "threshold": 0.5, "keep": "first"},
            "只在同帧、同 canonical label 内去重；实例级融合会保留中心明显不同的遮挡目标，并合并同一实例的全图/切片框。可按来源顺序保留首框，或优先保留未被切片边界截断的高分辨率定位框。",
            {
                "metric": _p("string", choices=("ios", "iou", "instance")),
                "threshold": _p("number", minimum=0.0, maximum=1.0),
                "keep": _p("string", choices=("first", "best_localization")),
            },
        ),
        OperatorDefinition(
            "objects.filter_by_phrase@1.0",
            "按检测短语筛选目标",
            "frame",
            {"objects": "EntitySet"},
            "ObjectSet",
            {"phrases": [], "mode": "include"},
            "按目标记录中的显式 detector phrase 做包含或排除分流；不读取标签语义，不执行隐藏推断。",
            {
                "phrases": _p("string_list", required=True),
                "mode": _p("string", choices=("include", "exclude")),
            },
        ),
        OperatorDefinition(
            "objects.filter_by_label@1.0",
            "按输出类别筛选目标",
            "frame",
            {"objects": "EntitySet"},
            "ObjectSet",
            {"labels": [], "mode": "include"},
            "按上游已经显式写入的 output label 做包含或排除分流；不重新解释视觉语义，也不按置信度竞争。",
            {
                "labels": _p("nonempty_string_list", required=True),
                "mode": _p("string", choices=("include", "exclude")),
            },
        ),
        OperatorDefinition(
            "objects.merge@1.0",
            "合并目标分支",
            "frame",
            {"objects": "EntitySet"},
            "ObjectSet",
            {},
            "按输入分支顺序合并多个显式 ObjectSet；不做隐藏去重或跨类别置信度竞争。",
        ),
        OperatorDefinition(
            "objects.filter_by_regions@1.0",
            "按标注区域筛选目标",
            "frame",
            {"objects": "EntitySet", "regions": "RegionSet"},
            "ObjectSet",
            {
                "membership_mode": "center",
                "overlap_threshold": 0.1,
                "keep": "inside",
                "empty_regions": "exclude",
            },
            "按全部实际标注区域的并集筛选目标；区域数量运行时确定，可用于检测结果、跟踪、统计和证据框的统一业务范围。空区域可明确选择排除全部或透传全部目标。",
            {
                "membership_mode": _p("string", choices=("center", "overlap")),
                "overlap_threshold": _p("number", minimum=0.0, maximum=1.0),
                "keep": _p("string", choices=("inside", "outside")),
                "empty_regions": _p("string", choices=("exclude", "passthrough")),
            },
        ),
        OperatorDefinition(
            "visual.color_fraction@1.0",
            "实体区域颜色占比",
            "frame",
            {"frames": "FrameSet", "objects": "EntitySet"},
            "ConditionSet",
            {
                "color": "white",
                "subject_region": [0.0, 0.15, 1.0, 0.7],
                "min_fraction": 0.2,
                "selection_mode": "fraction",
                "dominance_margin": 0.05,
                "color_tolerance": "strict",
            },
            "在每个实体框的归一化子区域内按固定 HSV 色域计算颜色像素占比，并与显式阈值比较。",
            {
                "color": _p("string", choices=(
                    *COLOR_NAMES,
                )),
                "subject_region": _p("normalized_box"),
                "min_fraction": _p("number", minimum=0.0, maximum=1.0),
                "selection_mode": _p("string", choices=("fraction", "dominant")),
                "dominance_margin": _p("number", minimum=0.0, maximum=1.0),
                "color_tolerance": _p("string", choices=("strict", "semantic")),
            },
        ),
        OperatorDefinition(
            "visual.geometry@1.0",
            "实体几何属性",
            "frame",
            {"objects": "EntitySet"},
            "ConditionSet",
            {
                "dimension": "size", "value": "medium", "size_mode": "relative",
                "small_max_area": 0.02, "large_min_area": 0.12,
                "position_margin": 0.33, "aspect_ratio_threshold": 1.0,
            },
            "根据归一化框面积、中心点位置或原媒体像素宽高比执行固定、可配置的几何判断。",
            {
                "dimension": _p("string", choices=("size", "position", "aspect_ratio")),
                "value": _p("string", choices=(
                    "small", "medium", "large", "left", "center", "right",
                    "top", "middle", "bottom", "horizontal", "vertical",
                )),
                "size_mode": _p("string", choices=("relative", "absolute")),
                "small_max_area": _p("number", minimum=0.0, maximum=1.0),
                "large_min_area": _p("number", minimum=0.0, maximum=1.0),
                "position_margin": _p("number", minimum=0.0, maximum=0.5),
                "aspect_ratio_threshold": _p("number", minimum=0.01, maximum=100.0),
            },
        ),
        OperatorDefinition(
            "region.full_frame@1.0",
            "全图区域",
            "frame",
            {"frames": "FrameSet"},
            "RegionSet",
            {},
            "生成覆盖原图 [0,1] 范围的区域。",
        ),
        OperatorDefinition(
            "region.manual@1.0",
            "手工区域",
            "media",
            {},
            "RegionSet",
            {"shape": "polygon", "points": []},
            "使用技能中显式保存的归一化多边形或矩形。",
            {"shape": _p("string", choices=("polygon", "rectangle")), "points": _p("point_list", required=True)},
        ),
        OperatorDefinition(
            "region.manual_set@1.0",
            "手工命名区域集合",
            "media",
            {},
            "RegionSet",
            {"regions": []},
            "使用技能中显式保存的一个或多个命名矩形/多边形；适合多车道、多危险区和多禁停区。",
            {"regions": _p("named_region_list", required=True)},
        ),
        OperatorDefinition(
            "region.from_objects@1.0",
            "检测结果转区域",
            "frame",
            {"objects": "ObjectSet"},
            "RegionSet",
            {"mode": "all"},
            "将检测框显式转换为区域，模式为 all、largest 或 union。",
            {"mode": _p("string", choices=("all", "largest", "union"))},
        ),
        OperatorDefinition(
            "regions.merge@1.0",
            "合并区域分支",
            "frame",
            {"regions": "RegionSet"},
            "RegionSet",
            {},
            "按输入分支顺序合并多个显式区域集合；保留每个区域的稳定 ID、标签和原始归一化坐标。",
        ),
        OperatorDefinition(
            "direction.manual@1.0",
            "手工方向",
            "media",
            {},
            "VectorSet",
            {"vector": [0.0, -1.0], "start": None, "end": None},
            "使用技能中显式配置的二维方向向量。",
            {
                "vector": _p("vector2", required=True),
                "start": _p("point_or_null"),
                "end": _p("point_or_null"),
            },
        ),
        OperatorDefinition(
            "direction.manual_set@1.0",
            "手工命名方向集合",
            "media",
            {},
            "VectorSet",
            {"directions": []},
            "保存一个或多个命名参考方向；方向 key 可与命名车道区域 ID 一一对应。",
            {"directions": _p("direction_list", required=True)},
        ),
        OperatorDefinition(
            "direction.image_axis@1.0",
            "画面坐标方向",
            "media",
            {},
            "VectorSet",
            {"direction": "right"},
            "把画面坐标系中的八个固定方向映射为可广播的单位向量；不绑定实体类别。",
            {
                "direction": _p("string", choices=(
                    "left", "right", "up", "down",
                    "up_left", "up_right", "down_left", "down_right",
                )),
            },
        ),
        OperatorDefinition(
            "track.iou@1.0",
            "IoU 跟踪",
            "stream",
            {"objects": "EntitySet"},
            "TrackSet",
            {
                "iou_threshold": 0.3,
                "max_missing_frames": 3,
                "same_label_only": True,
                "motion_consistency": False,
                "motion_prediction": False,
                "min_direction_cosine": -1.0,
                "min_motion_pixels": 5.0,
            },
            "按全帧一对一匹配当前位置 IoU；可叠加运动预测 IoU 与方向连续性，减少透视运动断轨及密集目标串轨。丢失阈值按抽样序列位置计算。",
            {
                "iou_threshold": _p("number", minimum=0.0, maximum=1.0),
                "max_missing_frames": _p("integer", minimum=0),
                "same_label_only": _p("boolean"),
                "motion_consistency": _p("boolean"),
                "motion_prediction": _p("boolean"),
                "min_direction_cosine": _p("number", minimum=-1.0, maximum=1.0),
                "min_motion_pixels": _p("number", minimum=0.0),
            },
        ),
        OperatorDefinition(
            "track.confirm@1.0",
            "轨迹确认",
            "stream",
            {"tracks": "TrackSet"},
            "TrackSet",
            {"min_hits": 2, "min_span_seconds": 0.5},
            "按显式最少命中帧数和首末命中时间跨度确认轨迹，过滤孤立单帧视觉噪声。",
            {
                "min_hits": _p("integer", minimum=1),
                "min_span_seconds": _p("number", minimum=0.0),
            },
        ),
        OperatorDefinition(
            "spatial.inside@1.0",
            "区域内判断",
            "frame",
            {"objects": "EntitySet", "region": "RegionSet"},
            "ConditionSet",
            {"mode": "center", "overlap_threshold": 0.5},
            "按目标框中心点或与区域的相交比例产生逐实体条件。",
            {
                "mode": _p("string", choices=("center", "overlap")),
                "overlap_threshold": _p("number", minimum=0.0, maximum=1.0),
            },
        ),
        OperatorDefinition(
            "spatial.associate@1.0",
            "目标关联",
            "frame",
            {"subjects": "EntitySet", "objects": "EntitySet"},
            "ConditionSet",
            {
                "relation": "overlap",
                "threshold": 0.1,
                "subject_region": [0.0, 0.0, 1.0, 0.35],
                "object_region": [0.0, 0.0, 1.0, 1.0],
                "same_source_only": False,
            },
            "按来源实体 ID、单向覆盖、双向同实例覆盖、near，或一个目标中心是否落在另一个目标的相对区域内产生逐主体关联条件；可显式限定局部证据只能回绑其来源主体。",
            {
                "relation": _p("string", choices=(
                    "source_entity", "overlap", "inside", "contains", "mutual_match", "near", "center_in_subject_region",
                    "center_in_object_region",
                    "best_owner",
                    "left_of", "right_of", "above", "below",
                )),
                "threshold": _p("number", minimum=0.0),
                "subject_region": _p("relative_box"),
                "object_region": _p("relative_box"),
                "same_source_only": _p("boolean"),
            },
        ),
        OperatorDefinition(
            "measure.count@1.0",
            "目标计数",
            "frame",
            {"entities": "CountableSet", "objects": "EntitySet"},
            "ScalarSet",
            {"scope": "frame", "group_by": "none"},
            "按显式作用域统计对象帧数、唯一轨迹或唯一事件；不把视频逐帧框累计成目标数量。",
            {
                "scope": _p(
                    "string", choices=("frame", "unique")
                ),
                "group_by": _p("string", choices=("none", "label")),
            },
            optional_inputs=frozenset({"entities", "objects"}),
        ),
        OperatorDefinition(
            "measure.speed@1.0",
            "像素速度",
            "stream",
            {"tracks": "TrackSet"},
            "ScalarSet",
            {"window_frames": 5, "unit": "pixels_per_second", "aggregation": "per_track"},
            "按轨迹中心点位移除以时间差计算像素速度。",
            {
                "window_frames": _p("integer", minimum=2),
                "unit": _p("string", choices=("pixels_per_second",)),
                "aggregation": _p(
                    "string",
                    choices=("per_track", "global_mean", "global_median"),
                ),
            },
        ),
        OperatorDefinition(
            "measure.region_count@1.0",
            "按命名区域计数",
            "stream",
            {"objects": "EntitySet", "regions": "RegionSet", "frames": "FrameSet"},
            "ScalarSet",
            {"membership_mode": "center"},
            "按每个采样帧分别统计目标中心落入各命名区域的数量；即使某区域为零也输出显式零值。",
            {"membership_mode": _p("string", choices=("center",))},
        ),
        OperatorDefinition(
            "measure.region_speed@1.0",
            "按命名区域速度",
            "stream",
            {"tracks": "TrackSet", "regions": "RegionSet"},
            "ScalarSet",
            {
                "window_frames": 5,
                "unit": "pixels_per_second",
                "aggregation": "median",
                "membership_mode": "sample_center",
            },
            "先计算轨迹像素速度，再按命名区域和采样时刻执行中位数或均值聚合。",
            {
                "window_frames": _p("integer", minimum=2),
                "unit": _p("string", choices=("pixels_per_second",)),
                "aggregation": _p("string", choices=("mean", "median")),
                "membership_mode": _p(
                    "string", choices=("sample_center", "majority_center")
                ),
            },
        ),
        OperatorDefinition(
            "measure.heading@1.0",
            "轨迹方向",
            "stream",
            {"tracks": "TrackSet"},
            "VectorSet",
            {
                "window_frames": 5,
                "min_displacement_pixels": 10.0,
                "min_displacement_box_ratio": 0.0,
            },
            "用轨迹窗口首尾中心点差得到归一化方向向量；可按目标框尺寸自适应小目标位移门槛。",
            {
                "window_frames": _p("integer", minimum=2),
                "min_displacement_pixels": _p("number", minimum=0.0),
                "min_displacement_box_ratio": _p("number", minimum=0.0, maximum=1.0),
            },
        ),
        OperatorDefinition(
            "measure.majority_heading@1.0",
            "多数方向",
            "stream",
            {"directions": "VectorSet"},
            "VectorSet",
            {"minimum_tracks": 3, "aggregation": "per_frame"},
            "按帧或按整段视频对有效轨迹方向求和归一化；全局模式先对每条轨迹等权汇总，再形成可广播参考方向。",
            {
                "minimum_tracks": _p("integer", minimum=1),
                "aggregation": _p("string", choices=("per_frame", "global")),
            },
        ),
        OperatorDefinition(
            "measure.lane_majority_heading@1.0",
            "按车道整段多数方向",
            "stream",
            {"tracks": "TrackSet", "directions": "VectorSet", "lanes": "RegionSet"},
            "VectorSet",
            {"minimum_tracks": 2, "membership_mode": "majority_center"},
            "先按命名车道区域归属轨迹，再在整段视频内对每条轨迹等权汇总，分别生成每车道参考方向。",
            {
                "minimum_tracks": _p("integer", minimum=1),
                "membership_mode": _p(
                    "string",
                    choices=("majority_center", "latest_center", "sample_center"),
                ),
            },
        ),
        OperatorDefinition(
            "logic.compare@1.0",
            "比较",
            "frame",
            {"left": "ValueSet", "right": "ValueSet"},
            "ConditionSet",
            {"operator": ">", "value": None, "threshold": -0.5, "overrides": {}, "operator_overrides": {}, "key_filter": None},
            "执行显式数值比较或方向余弦比较；数值比较可按稳定 key 覆盖默认阈值，也可限定到一个命名区域。",
            {
                "operator": _p("string", choices=(
                    ">", ">=", "<", "<=", "==", "!=",
                    "opposite_direction", "aligned_direction",
                )),
                "value": _p("number_or_null"),
                "threshold": _p("number", minimum=-1.0, maximum=1.0),
                "overrides": _p("numeric_mapping"),
                "operator_overrides": _p("string_mapping"),
                "key_filter": _p("string_or_null"),
            },
            optional_inputs=frozenset({"right"}),
        ),
        OperatorDefinition(
            "logic.heading_by_lane@1.0",
            "按车道比较方向",
            "stream",
            {
                "tracks": "TrackSet",
                "headings": "VectorSet",
                "lanes": "RegionSet",
                "references": "VectorSet",
            },
            "ConditionSet",
            {"threshold": -0.5, "membership_mode": "majority_center", "relation": "opposite", "scope_overrides": {}},
            "按轨迹所在命名区域选择参考方向，以显式 aligned/opposite 关系比较方向余弦；global 参考方向可作为广播后备；阈值和方向关系可按实际标注区域覆盖。",
            {
                "threshold": _p("number", minimum=-1.0, maximum=1.0),
                "membership_mode": _p(
                    "string",
                    choices=("majority_center", "latest_center", "sample_center"),
                ),
                "relation": _p("string", choices=("aligned", "opposite")),
                "scope_overrides": _p("json"),
            },
        ),
        OperatorDefinition(
            "logic.all@1.0",
            "全部成立",
            "frame",
            {"conditions": "ConditionSet"},
            "ConditionSet",
            {"combine_scope": "by_key"},
            "按相同 key 对多个条件执行逻辑与；也可按帧将各条件聚合为一个全局事件条件。",
            {"combine_scope": _p("string", choices=("by_key", "frame_any"))},
        ),
        OperatorDefinition(
            "logic.any@1.0",
            "任一成立",
            "frame",
            {"conditions": "ConditionSet"},
            "ConditionSet",
            {"combine_scope": "by_key"},
            "按相同 key 对多个条件执行逻辑或；也可按帧将各条件聚合为一个全局事件条件。",
            {"combine_scope": _p("string", choices=("by_key", "frame_any"))},
        ),
        OperatorDefinition(
            "logic.not@1.0",
            "条件取反",
            "frame",
            {"condition": "ConditionSet"},
            "ConditionSet",
            {},
            "对每个条件 key 执行逻辑取反。",
        ),
        OperatorDefinition(
            "filter.apply@1.0",
            "应用过滤条件",
            "frame",
            {"objects": "EntitySet", "condition": "ConditionSet"},
            "EntitySet",
            {"output_label": None},
            "仅保留对应 key 条件为真的实体。",
            {"output_label": _p("string_or_null")},
        ),
        OperatorDefinition(
            "tracks.filter@1.0",
            "按条件过滤轨迹",
            "stream",
            {"tracks": "TrackSet", "condition": "ConditionSet"},
            "TrackSet",
            {"history_mode": "matching_samples"},
            "按 track ID 和原始帧号过滤轨迹；可只保留条件命中的历史帧或保留整条命中轨迹。",
            {
                "history_mode": _p(
                    "string", choices=("matching_samples", "whole_track")
                ),
            },
        ),
        OperatorDefinition(
            "tracks.filter_by_events@1.0",
            "按事件过滤轨迹",
            "stream",
            {"tracks": "TrackSet", "events": "EventSet"},
            "TrackSet",
            {"time_window": "event"},
            "仅保留 entity_id 与事件匹配的轨迹；可保留事件起止时间窗内历史帧或整条轨迹。",
            {
                "time_window": _p(
                    "string", choices=("event", "whole_track")
                ),
            },
        ),
        OperatorDefinition(
            "objects.from_tracks@1.0",
            "轨迹转目标框",
            "stream",
            {"tracks": "TrackSet"},
            "ObjectSet",
            {"selection": "latest"},
            "从每条轨迹显式选择首帧框、最新框或全部历史框，产出可继续过滤、标注和导出的 ObjectSet。",
            {"selection": _p("string", choices=("first", "latest", "all"))},
        ),
        OperatorDefinition(
            "objects.relabel@1.0",
            "目标框重命名",
            "frame",
            {"objects": "EntitySet"},
            "ObjectSet",
            {"label": "目标"},
            "复制目标框集合并应用显式结果标签，不改变坐标、来源和跟踪 ID。",
            {"label": _p("string")},
        ),
        OperatorDefinition(
            "event.from_condition@1.0",
            "条件生成事件",
            "stream",
            {"condition": "ConditionSet"},
            "EventSet",
            {
                "seconds": 2.0,
                "scope": "track",
                "gap_tolerance_seconds": 0.5,
                "trigger_mode": "once",
                "label": "视觉事件",
            },
            "把逐实体或全局布尔条件按显式持续时长、间断容忍和触发模式原子化为 EventSet，并直接附加事件标签。",
            {
                "seconds": _p("number", minimum=0.0),
                "scope": _p("string", choices=("track", "global", "region")),
                "gap_tolerance_seconds": _p("number", minimum=0.0),
                "trigger_mode": _p("string", choices=("once", "repeat")),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "event.relabel@1.0",
            "事件重命名",
            "final",
            {"events": "EventSet"},
            "EventSet",
            {"label": "视觉事件"},
            "复制事件集合并应用显式业务标签，保留实体、起止时间和证据元数据。",
            {"label": _p("string")},
        ),
        OperatorDefinition(
            "temporal.hold@1.0",
            "条件短时保持",
            "stream",
            {"condition": "ConditionSet"},
            "ConditionSet",
            {"seconds": 1.0, "value": True},
            "按实体键因果保持最近出现的指定布尔值；只使用当前及历史证据，用于显式配置视频属性去抖。",
            {
                "seconds": _p("number", minimum=0.0),
                "value": _p("boolean"),
            },
        ),
        OperatorDefinition(
            "temporal.persist@1.0",
            "持续条件",
            "stream",
            {"condition": "ConditionSet"},
            "EventSet",
            {"seconds": 2.0, "scope": "track", "gap_tolerance_seconds": 0.5, "trigger_mode": "once", "scope_overrides": {}, "override_scope_field": "region_id"},
            "按 track 或 global key 连续满足条件达到时间后产生事件；上游携带区域身份时，持续、容错和触发方式可按实际标注区域覆盖。",
            {
                "seconds": _p("number", minimum=0.0),
                "scope": _p("string", choices=("track", "global", "region")),
                "gap_tolerance_seconds": _p("number", minimum=0.0),
                "trigger_mode": _p("string", choices=("once", "repeat")),
                "scope_overrides": _p("json"),
                "override_scope_field": _p("string"),
            },
        ),
        OperatorDefinition(
            "temporal.qualify@1.0",
            "通用持续资格",
            "stream",
            {"condition": "ConditionSet"},
            "EventSet",
            {
                "mode": "continuous",
                "duration_seconds": 0.0,
                "allowed_gap_seconds": 0.0,
                "window_seconds": None,
                "required_ratio": 1.0,
                "trigger_mode": "once",
                "identity_scope": "source",
            },
            "按同一身份支持立即、连续、累计和窗口占比持续资格。",
            {
                "mode": _p("string", choices=("immediate", "continuous", "cumulative", "ratio")),
                "duration_seconds": _p("number", minimum=0),
                "allowed_gap_seconds": _p("number", minimum=0),
                "window_seconds": _p("number_or_null", minimum=0),
                "required_ratio": _p("number", minimum=0, maximum=1),
                "trigger_mode": _p("string", choices=("once", "continuous")),
                "identity_scope": _p("string", choices=("source", "global", "object", "track", "pair", "region")),
            },
        ),
        OperatorDefinition(
            "temporal.event_duration@1.0",
            "事件时长筛选",
            "stream",
            {"events": "EventSet"},
            "EventSet",
            {"minimum_seconds": 0.0, "label": ""},
            "按事件自身起止时间筛选持续时长。",
            {
                "minimum_seconds": _p("number", minimum=0),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "temporal.join@1.0",
            "多分支事件汇合",
            "stream",
            {"events": "EventSet"},
            "EventSet",
            {
                "mode": "all_active",
                "required_count": None,
                "window_seconds": None,
                "correlation_scope": "global",
                "correlation_fields": [],
                "maximum_matches": 1000,
                "label": "组合事件",
            },
            "支持同时有效、全部完成、窗口内完成、任一和N选M的动态多分支汇合。",
            {
                "mode": _p("string", choices=("all_active", "all_completed", "all_completed_within_window", "any", "n_of_m", "exclusive", "overlap")),
                "required_count": _p("integer_or_null", minimum=1),
                "window_seconds": _p("number_or_null", minimum=0),
                "correlation_scope": _p("string", choices=("global", "object", "track", "pair", "region", "camera", "scene", "field")),
                "correlation_fields": _p("json"),
                "maximum_matches": _p("integer", minimum=1),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "temporal.sequence@2.0",
            "通用事件顺序",
            "stream",
            {"events": "EventSet"},
            "EventSet",
            {
                "transitions": [],
                "correlation_scope": "global",
                "correlation_fields": [],
                "consume_events": True,
                "label": "顺序事件",
            },
            "每两个阶段可独立配置最小与最大间隔，并按目标或业务字段关联。",
            {
                "transitions": _p("json"),
                "correlation_scope": _p("string", choices=("global", "object", "track", "pair", "region", "camera", "scene", "field")),
                "correlation_fields": _p("json"),
                "consume_events": _p("boolean"),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "temporal.absence@1.0",
            "时间窗缺失",
            "stream",
            {"anchors": "EventSet", "forbidden": "EventSet"},
            "EventSet",
            {"before_seconds": 0.0, "after_seconds": 0.0, "same_key": False, "label": "缺失事件"},
            "判断锚点事件前后指定窗口内没有出现禁止事件。",
            {
                "before_seconds": _p("number", minimum=0),
                "after_seconds": _p("number", minimum=0),
                "same_key": _p("boolean"),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "temporal.repeat@1.0",
            "时间窗重复",
            "stream",
            {"events": "EventSet"},
            "EventSet",
            {"window_seconds": 60.0, "minimum_count": 2, "same_key": True, "label": "重复事件"},
            "判断同一目标或全局事件在时间窗内至少重复指定次数。",
            {
                "window_seconds": _p("number", minimum=0),
                "minimum_count": _p("integer", minimum=2),
                "same_key": _p("boolean"),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "event.trigger@2.0",
            "事件触发策略",
            "event",
            {"events": "EventSet"},
            "EventSet",
            {
                "repeat_policy": "allow_repeat",
                "cooldown_seconds": 0.0,
                "cooldown_scope": "entity",
                "severity": "medium",
                "notification_enabled": False,
                "label": "",
            },
            "只控制首次/重复、冷却、级别和通知，不承载事件条件含义。",
            {
                "repeat_policy": _p("string", choices=("allow_repeat", "first_only")),
                "cooldown_seconds": _p("number", minimum=0),
                "cooldown_scope": _p("string", choices=("entity", "global")),
                "severity": _p("string", choices=("low", "medium", "high", "critical")),
                "notification_enabled": _p("boolean"),
                "label": _p("string"),
            },
        ),
        OperatorDefinition(
            "output.draw@1.0",
            "结果绘制",
            "final",
            {
                "frames": "FrameSet",
                "objects": "EntitySet",
                "events": "EventSet",
                "regions": "RegionSet",
                "directions": "VectorSet",
                "measurements": "ScalarSet",
            },
            "RenderedMedia",
            {
                "show_labels": True,
                "show_event_labels": True,
                "show_track_id": True,
                "show_trajectory": False,
                "show_regions": True,
                "show_directions": True,
                "show_measurements": True,
                "event_time_window": "event",
                "output_size_mode": "source",
                "output_width": None,
                "output_height": None,
                "output_fps_mode": "sample_timeline",
                "output_fps": None,
            },
            "在原始媒体坐标上绘制目标、轨迹、区域和事件。",
            {
                "show_labels": _p("boolean"),
                "show_event_labels": _p("boolean"),
                "show_track_id": _p("boolean"),
                "show_trajectory": _p("boolean"),
                "show_regions": _p("boolean"),
                "show_directions": _p("boolean"),
                "show_measurements": _p("boolean"),
                "event_time_window": _p(
                    "string", choices=("event", "track_history")
                ),
                "output_size_mode": _p(
                    "string", choices=("source", "processed", "fixed")
                ),
                "output_width": _p("integer_or_null", minimum=1),
                "output_height": _p("integer_or_null", minimum=1),
                "output_fps_mode": _p(
                    "string", choices=("sample_timeline", "source", "fixed")
                ),
                "output_fps": _p("number_or_null", minimum=0.01),
            },
            optional_inputs=frozenset({
                "objects", "events", "regions", "directions", "measurements"
            }),
        ),
        OperatorDefinition(
            "output.alert@1.0",
            "事件输出",
            "final",
            {"events": "EventSet"},
            "EventSet",
            {"label": "视觉事件"},
            "将事件集合转换为统一可导出的事件记录。",
            {"label": _p("string")},
        ),
        OperatorDefinition(
            "set.partition@1.0",
            "集合动态分组",
            "entity",
            {"entities": "EntitySet", "regions": "RegionSet"},
            "ScopedSet",
            {"mode": "global"},
            "按全局、标签或当前场景的动态区域集合划分对象或轨迹。",
            {"mode": _p("string", choices=("global", "label", "region"))},
            optional_inputs=frozenset({"regions"}),
        ),
        OperatorDefinition(
            "set.difference@1.0",
            "集合排除",
            "entity",
            {"left": "EntitySet", "right": "EntitySet"},
            "EntitySet",
            {"field": "identity"},
            "按身份、标签或检测短语从左侧集合中显式排除右侧集合。",
            {"field": _p("string", choices=("identity", "label", "phrase"))},
        ),
        OperatorDefinition(
            "set.semi_join@1.0",
            "保留已关联主体",
            "entity",
            {"subjects": "EntitySet", "pairs": "PairSet"},
            "EntitySet",
            {},
            "根据显式 PairSet 保留至少存在一个匹配对象的主体。",
        ),
        OperatorDefinition(
            "set.anti_join@1.0",
            "保留未关联主体",
            "entity",
            {"subjects": "EntitySet", "pairs": "PairSet"},
            "EntitySet",
            {},
            "根据显式 PairSet 保留没有匹配对象的主体，用于逐主体缺失关系。",
        ),
        OperatorDefinition(
            "pairs.build@1.0",
            "构建目标对",
            "entity_pair",
            {"subjects": "EntitySet", "objects": "EntitySet"},
            "PairSet",
            {"same_source_only": False},
            "按同一采样帧构建主体与对象候选对，不提前混入阈值判断。",
            {"same_source_only": _p("boolean")},
        ),
        OperatorDefinition(
            "pairs.measure@1.0",
            "目标对关系测量",
            "entity_pair",
            {"pairs": "PairSet"},
            "PairSet",
            {},
            "为目标对计算 IoU、IoS、双方覆盖率与中心距离。",
        ),
        OperatorDefinition(
            "pairs.filter@1.0",
            "目标对阈值过滤",
            "entity_pair",
            {"pairs": "PairSet"},
            "PairSet",
            {"metric": "iou", "operator": ">=", "threshold": 0.3},
            "按显式关系度量、比较符和阈值筛选目标对。",
            {
                "metric": _p("string", choices=(
                    "iou", "ios", "subject_coverage", "object_coverage", "center_distance"
                )),
                "operator": _p("string", choices=(">", ">=", "<", "<=")),
                "threshold": _p("number", minimum=0.0),
            },
        ),
        OperatorDefinition(
            "reduce.count@1.0",
            "通用集合计数",
            "aggregate",
            {"sets": "CountableSet"},
            "ScalarSet",
            {},
            "对普通集合逐帧计数，或对 ScopedSet 的每个动态范围分别计数。",
        ),
        OperatorDefinition(
            "reduce.exists@1.0",
            "集合存在归约",
            "aggregate",
            {"sets": "CountableSet"},
            "ConditionSet",
            {"scope": "global"},
            "将目标、轨迹、目标对或动态分组显式归约为存在条件；可保留实体身份供逐目标持续判断。",
            {"scope": _p("string", choices=("global", "entity"))},
        ),
        OperatorDefinition(
            "reduce.all@1.0",
            "条件全局归约",
            "aggregate",
            {"conditions": "ConditionSet"},
            "ConditionSet",
            {},
            "将每个时间点的分组条件归约为全局全部满足条件。",
        ),
        OperatorDefinition(
            "reduce.statistic@1.0",
            "通用统计归约",
            "aggregate",
            {"values": "ValueSet"},
            "ScalarSet",
            {"statistic": "mean"},
            "按key和时间计算均值、中位数、最小值、最大值或总和。",
            {"statistic": _p("string", choices=("mean", "median", "min", "max", "sum"))},
        ),
        OperatorDefinition(
            "reduce.quantify@1.0",
            "动态范围量词",
            "aggregate",
            {"conditions": "ConditionSet"},
            "ConditionSet",
            {"mode": "for_each", "required_count": 1, "combine_scope": "by_key"},
            "对未知数量的动态范围执行逐范围、任一、全部或至少N个量词。",
            {
                "mode": _p("string", choices=("for_each", "any", "all", "n_of_m")),
                "required_count": _p("integer", minimum=1),
                "combine_scope": _p("string", choices=("by_key", "frame_any")),
            },
        ),
        OperatorDefinition(
            "state.detect@1.0",
            "目标状态识别",
            "condition",
            {"entities": "EntitySet"},
            "StateSet",
            {
                "evidence_mode": "label",
                "state_labels": {},
                "default_state": "unknown",
                "positive_state": "positive",
                "threshold": 1.0,
            },
            "将检测类别、短语或几何特征转换为同一目标的状态观测。",
            {
                "evidence_mode": _p("string", choices=("label", "phrase", "aspect_ratio")),
                "state_labels": _p("string_mapping"),
                "default_state": _p("string"),
                "positive_state": _p("string"),
                "threshold": _p("number", minimum=0),
            },
        ),
        OperatorDefinition(
            "state.transition@1.0",
            "目标状态转变",
            "condition",
            {"states": "StateSet"},
            "ConditionSet",
            {
                "from_state": "normal",
                "to_state": "abnormal",
                "max_seconds": 5.0,
                "consume_source": True,
            },
            "按同一目标识别限定时间内的状态转变，而非仅判断当前状态。",
            {
                "from_state": _p("string"),
                "to_state": _p("string"),
                "max_seconds": _p("number", minimum=0),
                "consume_source": _p("boolean"),
            },
        ),
        OperatorDefinition(
            "evidence.collect@1.0",
            "证据收集",
            "event",
            {
                "objects": "ObjectSet",
                "tracks": "TrackSet",
                "pairs": "PairSet",
                "states": "StateSet",
                "measurements": "ScalarSet",
                "directions": "VectorSet",
            },
            "EvidenceSet",
            {},
            "将对象、轨迹、目标对、状态、数值和方向统一转换为可关联证据。",
            optional_inputs=frozenset({"objects", "tracks", "pairs", "states", "measurements", "directions"}),
        ),
        OperatorDefinition(
            "event.attach_evidence@1.0",
            "事件证据绑定",
            "event",
            {
                "events": "EventSet",
                "objects": "ObjectSet",
                "tracks": "TrackSet",
                "pairs": "PairSet",
                "measurements": "ScalarSet",
                "directions": "VectorSet",
                "evidence": "EvidenceSet",
            },
            "EventSet",
            {},
            "按事件实体身份绑定对象、轨迹、目标对、数值和方向证据。",
            optional_inputs=frozenset({"objects", "tracks", "pairs", "measurements", "directions", "evidence"}),
        ),
        OperatorDefinition(
            "result.project@1.0",
            "统一结果投影",
            "final",
            {
                "objects": "ObjectSet",
                "tracks": "TrackSet",
                "events": "EventSet",
                "measurements": "ScalarSet",
                "regions": "RegionSet",
                "directions": "VectorSet",
            },
            "ResultItemSet",
            {},
            "将专业结果投影为统一可索引结果项，同时保留原始结果通道。",
            optional_inputs=frozenset({"objects", "tracks", "events", "measurements", "regions", "directions"}),
        ),
    ]
    return OperatorRegistry(definitions)


__all__ = [
    "OperatorDefinition",
    "OperatorRegistry",
    "ParameterSpec",
    "build_default_registry",
]
