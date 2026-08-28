from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeDefinition:
    recipe_id: str
    display_name: str
    atoms: tuple[str, ...]
    purpose: str


_RECIPES = (
    RecipeDefinition(
        "target_in_dynamic_scopes",
        "动态区域内目标",
        ("set.partition@1.0", "reduce.quantify@1.0"),
        "对运行前数量未知的区域逐个、任一、全部或N选M判断。",
    ),
    RecipeDefinition(
        "same_subject_attributes",
        "同一主体多证据归属",
        ("pairs.build@1.0", "pairs.measure@1.0", "pairs.filter@1.0", "set.semi_join@1.0"),
        "确保多个属性、部件或关联物证据属于同一主体，禁止跨目标拼接。",
    ),
    RecipeDefinition(
        "equipment_absence",
        "主体缺少关联物",
        ("pairs.build@1.0", "pairs.measure@1.0", "pairs.filter@1.0", "set.anti_join@1.0"),
        "表达主体未关联指定对象、部件或可见证据的缺失关系。",
    ),
    RecipeDefinition(
        "state_change_event",
        "同一目标状态转变",
        ("state.detect@1.0", "state.transition@1.0", "temporal.qualify@1.0"),
        "表达任意可观察状态的转变，而非仅检测当前状态。",
    ),
    RecipeDefinition(
        "reverse_motion",
        "相对参考方向反向运动",
        ("track.iou@1.0", "measure.heading@1.0", "logic.compare@1.0", "temporal.qualify@1.0"),
        "按同一目标轨迹、动态区域和参考方向判断持续反向运动。",
    ),
    RecipeDefinition(
        "multi_branch_join",
        "多分支事件汇合",
        ("temporal.qualify@1.0", "temporal.join@1.0", "event.attach_evidence@1.0"),
        "组合独立持续的区域、计数、状态、方向和其它事件分支。",
    ),
    RecipeDefinition(
        "ordered_process",
        "有时限的阶段流程",
        ("temporal.qualify@1.0", "temporal.sequence@2.0", "event.attach_evidence@1.0"),
        "先完成A，再在独立时间窗内完成B、C，最终判定流程成功。",
    ),
    RecipeDefinition(
        "negative_or_repeated_event",
        "缺失或重复事件",
        ("temporal.absence@1.0", "temporal.repeat@1.0"),
        "表达规定窗口内未发生某事，或同一事件重复至少N次。",
    ),
)


def build_recipe_catalog() -> dict[str, RecipeDefinition]:
    return {item.recipe_id: item for item in _RECIPES}


__all__ = ["RecipeDefinition", "build_recipe_catalog"]
