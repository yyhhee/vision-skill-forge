"""User-facing constants and read-only condition projections."""

from __future__ import annotations

# Legacy imports intentionally re-export the same names.
# ruff: noqa: PLC0414
from typing import Any

from application.v2.support import MEDIA_CHOICES as MEDIA_CHOICES
from ui.event_rule_editor import parameter_table_rows

NO_ANNOTATION_SLOT = "__no_annotation_required__"

SUPPORTED_BUSINESS_PARAMETER_EDITORS = {
    "text",
    "number",
    "select",
    "multi_select",
    "percentage",
    "duration",
    "frames",
    "angle_degrees",
    "scene_resource_select",
    "direction_resource_select",
    "source_select",
    "boolean",
    "condition_tree",
    "readonly",
}

ANNOTATION_GUIDANCE_MARKDOWN = """
<section class="vs-section">
  <h2>仅当技能要求命名区域或方向参考时才需要标注</h2>
  <p class="vs-section-copy"><strong>什么时候需要这一步：</strong>技能涉及“在哪里”“朝哪个参考方向”或“区域之间的关系”时才标注，例如进入限制区、区域内计数、危险区域逗留、沿指定方向运动。普通的检测人/车/物可直接运行。</p>
  <div class="vs-guide">
    <div class="vs-guide-item"><b>矩形</b><span>按住拖拽框出规则区域，适合检测区、限制区。</span></div>
    <div class="vs-guide-item"><b>多边形</b><span>沿边界逐点点击，适合不规则区域。</span></div>
    <div class="vs-guide-item"><b>方向箭头</b><span>拖出规则所需的参考方向；箭头含义由当前技能规则决定。</span></div>
    <div class="vs-guide-item"><b>画完要保存</b><span>点“保存标注到技能”才会真正生效，可删除重画。</span></div>
  </div>
</section>
"""


def effective_condition_config_rows(
    parameter_rows: list[dict[str, Any]],
    condition_rows: list[dict[str, Any]],
    selected_condition: str | None,
) -> list[list[str]]:
    """Append the effective A/B evidence chains to the read-only config table.

    The editable parameters belong to one atom (for example ``attribute.color``),
    while the executed rule may combine several evidence paths.  Keeping these
    paths visible in the table prevents the base detector and its evidence
    verifier from appearing as one duplicated condition.  This projection is
    metadata only; parameter editing still uses ``parameter_rows`` unchanged.
    """

    table = parameter_table_rows(parameter_rows)
    if not selected_condition:
        return table
    group = next(
        (
            row
            for row in condition_rows
            if selected_condition
            in (row.get("verification_child_ids") or row.get("logic_child_ids") or [])
            and (row.get("verification_members") or row.get("member_summaries"))
        ),
        None,
    )
    if group is None:
        return table
    members = group.get("verification_members") or []
    if not members:
        by_id = {row.get("condition_id"): row for row in condition_rows}
        members = [
            {
                "name": by_id.get(condition_id, {}).get("name") or "条件",
                "summary": by_id.get(condition_id, {}).get("summary") or "",
            }
            for condition_id in (group.get("logic_child_ids") or [])
        ]
    for index, member in enumerate(members):
        label = f"条件 {chr(65 + index) if index < 26 else index + 1}"
        table.append(
            [
                label,
                str(member.get("name") or "复核证据"),
                "",
                "LLM业务编排 + 系统确定性编译",
                str(member.get("summary") or ""),
            ]
        )
    logic = str(
        group.get("verification_logic") or group.get("logic_relation_label") or ""
    ).strip()
    if logic and len(members) > 1:
        labels = [
            f"条件 {chr(65 + index) if index < 26 else index + 1}"
            for index in range(len(members))
        ]
        combination_text = (
            f"{logic}（{'、'.join(labels)}）"
            if logic.startswith("至少")
            else f" {logic} ".join(f"（{label}）" for label in labels)
        )
        table.append(
            [
                "最终复核组合",
                combination_text,
                "",
                "LLM业务编排 + 系统确定性编译",
                "只有组合规则满足时，才输出对应的最终业务结果。",
            ]
        )
    return table
