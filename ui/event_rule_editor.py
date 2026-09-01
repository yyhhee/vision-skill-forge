from __future__ import annotations

import html
import json
from typing import Any


_CHOICE_LABELS = {
    ">": "大于（>）", ">=": "大于等于（>=）", "==": "等于（==）",
    "<=": "小于等于（<=）", "<": "小于（<）", "!=": "不等于（!=）",
    "include": "保留所选类别", "exclude": "排除所选类别",
    "whole": "整个目标", "upper_clothing": "上衣", "lower_clothing": "裤子",
    "center": "框中心在区域内", "latest_center": "最新框中心在区域内",
    "sample_center": "逐帧框中心归属", "majority_center": "多数帧中心归属",
    "overlap": "框与区域有任意重叠", "overlap_ratio": "框与区域达到最低重叠比例",
    "inside": "位于内部", "contain": "包含", "region": "同一区域",
    "global": "全局", "frame": "同一画面", "track": "同一轨迹",
    "unique": "按唯一目标", "by_key": "按同一对象或区域",
    "frame_any": "按同一画面汇总", "camera": "同一相机", "scene": "同一场景",
    "object": "同一目标", "pair": "同一目标对", "field": "按指定字段",
    "mean": "平均值", "median": "中位数", "min": "最小值", "max": "最大值",
    "sum": "总和", "global_mean": "全局平均值", "global_median": "全局中位数",
    "per_frame": "每帧分别统计", "per_track": "每条轨迹分别统计",
    "for_each": "每项分别判断", "all": "全部", "any": "任一",
    "n_of_m": "至少 N 项", "all_active": "全部同时有效",
    "exclusive": "互斥选择",
    "all_completed": "全部完成", "all_completed_within_window": "窗口内全部完成",
    "continuous": "连续满足", "cumulative": "累计满足", "ratio": "窗口占比",
    "immediate": "立即", "once": "首次满足触发", "repeat": "再次满足可重复触发",
    "allow_repeat": "允许重复", "first_only": "仅首次",
    "identity": "同一身份", "label": "同一类别", "none": "不分组",
    "matching_samples": "仅匹配样本", "whole_track": "整条轨迹",
    "pixels_per_second": "像素/秒", "source": "跟随源媒体",
    "processed": "跟随处理尺寸", "fixed": "固定值", "sample_timeline": "跟随抽帧时间线",
    "fps": "按目标帧率", "frame_step": "按固定帧间隔", "interval": "按固定时间间隔",
    "long_side": "限制长边", "stretch": "拉伸到固定尺寸",
    "nearest": "最近邻", "bilinear": "双线性", "bicubic": "双三次",
    "ios": "交叠比例（IoS）", "iou": "交并比（IoU）", "keep_larger": "保留较大框",
    "best_localization": "优先保留定位更准的框",
    "center_distance": "中心距离", "object_coverage": "对象框覆盖比例",
    "subject_coverage": "主体框覆盖比例", "mutual_match": "双向匹配",
    "source_entity": "沿用来源目标", "best_owner": "最佳归属",
    "center_in_subject_region": "中心位于主体指定部位",
    "center_in_object_region": "中心位于关联目标指定部位",
    "source_entity": "沿用来源目标的复核证据", "near": "接近",
    "contains": "主体包含对象", "left_of": "位于左侧", "right_of": "位于右侧",
    "above": "位于上方", "below": "位于下方", "aligned": "方向一致",
    "opposite": "方向相反", "aligned_direction": "同向", "opposite_direction": "逆向",
    "aspect_ratio": "宽高比", "position": "位置", "size": "尺寸",
    "dominant": "主导类别", "fraction": "类别占比", "phrase": "检测描述",
    "critical": "严重", "high": "高", "medium": "中", "low": "低",
    "rectangle": "矩形", "polygon": "多边形", "absolute": "绝对尺寸", "relative": "相对尺寸",
    "first": "第一个", "latest": "最新一个", "largest": "最大一个", "union": "合并",
    "black": "黑色", "blue": "蓝色", "brown": "棕色", "cyan": "青色",
    "gray": "灰色", "green": "绿色", "orange": "橙色", "pink": "粉色",
    "purple": "紫色", "red": "红色", "white": "白色", "yellow": "黄色",
    "up": "向上", "down": "向下", "left": "向左", "right": "向右",
    "up_left": "左上", "up_right": "右上", "down_left": "左下", "down_right": "右下",
    "horizontal": "水平", "vertical": "垂直", "top": "顶部", "middle": "中部",
    "bottom": "底部", "small": "小", "medium": "中", "large": "大",
    # Keep these labels independent of the number of members in a group.
    # A two-member example may be shown as A/B, but real LLM plans can have
    # C, D, … or nested groups as well.
    "AND": "全部条件同时满足", "OR": "任一条件满足",
    "FRACTION_ONLY": "仅颜色占比", "SEMANTIC_ONLY": "仅模型属性证据",
}


def friendly_choice_label(value: Any) -> str:
    return _CHOICE_LABELS.get(str(value), str(value))


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, list) and all(not isinstance(item, (list, dict)) for item in value):
        return json.dumps([friendly_choice_label(item) for item in value], ensure_ascii=False)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return friendly_choice_label(value)


def parse_display_value(value: Any, editor: str) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    if editor in {"number", "duration", "percentage", "angle_degrees"}:
        return float(text)
    if editor == "frames":
        return int(float(text))
    if editor == "boolean":
        return text.lower() in {"是", "true", "1", "yes", "启用"}
    if editor == "multi_select":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in text.replace("，", ",").split(",")]
        return parsed if isinstance(parsed, list) else [parsed]
    return text


def parameter_table_rows(rows: list[dict[str, Any]]) -> list[list[str]]:
    return [
        [
            row["name"],
            display_value(row["value"]),
            row["unit"],
            row["source"],
            row["help"],
        ]
        for row in rows
    ]


def parse_parameter_table(
    table: list[list[Any]] | None,
    schema_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    by_name = {row["name"]: row for row in schema_rows}
    result = {}
    for raw in table or []:
        if not raw:
            continue
        name = str(raw[0]).strip()
        schema = by_name.get(name)
        if schema is None:
            continue
        value = raw[1] if len(raw) > 1 else None
        result[schema["parameter_id"]] = parse_display_value(
            value, schema["editor"]
        )
    return result


def render_condition_tree(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            '<section class="vs-empty-card"><b>这个分支还没有条件</b>'
            '<span>从下方能力列表新增第一个条件。系统会根据媒体类型只显示可执行能力。</span></section>'
        )
    root = next((row for row in rows if row.get("parent_id") is None), rows[0])
    formula = html.escape(
        str(
            root.get("effective_formula")
            or root.get("summary")
            or root.get("name")
            or ""
        )
    )
    is_workflow = root.get("formula_kind") == "workflow"
    formula_card = (
        '<section class="vs-rule-formula" aria-label="当前生效条件组合">'
        f'<b>{"当前生效流程" if is_workflow else "当前生效组合"}</b>'
        f'<code>{formula}</code>'
        f'<span>{"箭头表示处理先后；只有带 AND / OR / NOT 标记的步骤才是逻辑组合。" if is_workflow else "括号表示嵌套层级；AND、OR、NOT 按显示顺序执行。"}</span>'
        '</section>'
    )
    cards = []
    projected_child_ids = {
        child_id
        for item in rows
        for child_id in (item.get("verification_child_ids") or [])
    }
    for row in rows:
        if is_workflow and row.get("kind") == "导入判定":
            continue
        if row.get("condition_id") in projected_child_ids:
            continue
        depth = min(int(row.get("display_depth", row.get("depth", 0))), 6)
        name = html.escape(str(row.get("name") or "未命名条件"))
        summary = html.escape(str(row.get("summary") or ""))
        category = html.escape(str(row.get("category") or ""))
        status = html.escape(str(row.get("status") or ""))
        logic = str(row.get("logic") or "")
        relation = ""
        if row.get("logic_member_label"):
            relation = (
                '<span class="vs-condition-badge">'
                f'{html.escape(str(row["logic_member_label"]))}</span>'
            )
        elif row.get("kind") == "条件组":
            displayed_logic = (
                str(row.get("verification_logic") or "")
                if row.get("verification_members")
                else logic
            )
            relation = (
                f'<span class="vs-logic-badge">{html.escape(displayed_logic)}</span>'
                if displayed_logic
                else ""
            )
        elif row.get("workflow_role") == "evidence_branch":
            relation = '<span class="vs-condition-badge">证据分支</span>'
        elif row.get("workflow_index"):
            relation = (
                f'<span class="vs-step-badge">步骤 {int(row["workflow_index"])}</span>'
            )
        state_class = "is-ready" if status in {"已配置", "可用"} else "is-pending"
        if status == "已停用":
            state_class = "is-disabled"
        logic_members = ""
        verification_members = row.get("verification_members") or []
        member_summaries = (
            [member.get("name", "") for member in verification_members]
            if verification_members
            else row.get("member_summaries") or []
        )
        if member_summaries:
            relation_label = html.escape(
                str(
                    row.get("verification_logic")
                    if verification_members
                    else row.get("logic_relation_label") or logic
                )
            )
            parts = []
            for index, member in enumerate(member_summaries):
                if index:
                    parts.append(
                        f'<b class="vs-logic-connector">{relation_label}</b>'
                    )
                member_label = (
                    f"条件 {chr(65 + index)}"
                    if index < 26
                    else f"条件 {index + 1}"
                )
                parts.append(
                    '<span class="vs-logic-member">'
                    f'<i>{member_label}</i>{html.escape(str(member))}</span>'
                )
            logic_members = (
                '<div class="vs-logic-members" aria-label="条件组成员">'
                + "".join(parts)
                + "</div>"
            )
        summary_html = (
            ""
            if member_summaries and not is_workflow
            else f"<p>{summary}</p>"
        )
        cards.append(
            f'<article class="vs-rule-node {state_class}{" is-workflow-step" if row.get("imported_step") else ""}{" is-logic-group" if member_summaries else ""}" style="--rule-depth:{depth}">'
            f'<div class="vs-rule-node-head"><span class="vs-rule-category">{category}</span>{relation}'
            f'<span class="vs-rule-status">{status}</span></div>'
            f'<strong>{name}</strong>{summary_html}{logic_members}</article>'
        )
        for index, member in enumerate(verification_members):
            member_name = html.escape(str(member.get("name") or "复核证据"))
            member_summary = html.escape(str(member.get("summary") or ""))
            member_label = (
                f"条件 {chr(65 + index)}"
                if index < 26
                else f"条件 {index + 1}"
            )
            cards.append(
                '<article class="vs-rule-node is-ready" '
                f'style="--rule-depth:{min(depth + 1, 6)}">'
                '<div class="vs-rule-node-head">'
                '<span class="vs-rule-category">目标与属性</span>'
                f'<span class="vs-condition-badge">{member_label}</span>'
                '<span class="vs-rule-status">已配置</span></div>'
                f'<strong>{member_name}</strong><p>{member_summary}</p></article>'
            )
    return formula_card + '<section class="vs-rule-tree">' + "".join(cards) + "</section>"


def render_branch_pattern(
    mode: str,
    branch_names: list[str],
    *,
    required_count: int | None = None,
    window_seconds: float | None = None,
    correlation_scope: str = "global",
) -> str:
    """Render the effective cross-branch completion rule as a business formula."""

    names = [html.escape(str(name)) for name in branch_names if str(name).strip()]
    if mode == "none" or len(names) < 2:
        return (
            '<section class="vs-rule-formula" aria-label="当前生效分支编排">'
            '<b>当前生效分支编排</b><code>尚未编排分支</code>'
            '<span>创建两个及以上分支后，可选择顺序、并行、互斥、任意完成或部分汇聚。</span>'
            '</section>'
        )

    relation_labels = {
        "sequence": "顺序",
        "all_completed": "并行",
        "all_active": "并行（同时有效）",
        "all_completed_within_window": "并行（限时完成）",
        "exclusive": "互斥选择",
        "any": "任意完成（或）",
        "n_of_m": "部分汇聚",
    }
    if mode == "sequence":
        formula = " → ".join(names) + " → 阶段完成"
        meaning = "前一分支完成后才接受下一分支，按显示顺序逐个完成。"
    elif mode == "n_of_m":
        count = max(1, int(required_count or 1))
        formula = f"至少 {count} 项完成（" + "、".join(names) + "）→ 阶段完成"
        meaning = "所选分支中达到指定完成数量后，本阶段完成。"
    else:
        connector = {
            "all_completed": " AND ",
            "all_active": " AND ",
            "all_completed_within_window": " AND ",
            "exclusive": " XOR ",
            "any": " OR ",
        }.get(mode, "、")
        formula = connector.join(names) + " → 阶段完成"
        meaning = {
            "all_completed": "所有所选分支都完成后，本阶段完成；分支可同时进行。",
            "all_active": "所有所选分支必须在同一时刻处于有效状态。",
            "all_completed_within_window": "所有分支须在限定时间窗内完成。",
            "exclusive": "只采用最先完成的一个分支，其它候选分支不再参与本阶段。",
            "any": "任意一个所选分支完成，本阶段即完成。",
        }.get(mode, "按当前关系组合所选分支。")

    scope_labels = {
        "global": "整个媒体共同判断",
        "object": "按同一目标判断",
        "track": "按同一轨迹判断",
        "pair": "按同一目标对判断",
        "region": "按同一区域判断",
        "camera": "按同一相机判断",
        "scene": "按同一场景判断",
    }
    extras = [meaning, scope_labels.get(correlation_scope, correlation_scope)]
    if window_seconds is not None and float(window_seconds) > 0:
        extras.append(f"时间限制：{float(window_seconds):g} 秒")
    return (
        '<section class="vs-rule-formula" aria-label="当前生效分支编排">'
        f'<b>当前生效分支编排 · {html.escape(relation_labels.get(mode, mode))}</b>'
        f'<code>{formula}</code><span>{html.escape("；".join(extras))}</span>'
        '</section>'
    )


def render_branch_overview(
    branches: list[dict[str, Any]], selected_branch_id: str | None
) -> str:
    if not branches:
        return '<div class="vs-empty-card">当前媒体流程还没有业务分支。</div>'
    items = []
    for index, branch in enumerate(branches, start=1):
        active = branch["branch_id"] == selected_branch_id
        css = " is-selected" if active else ""
        name = html.escape(str(branch["display_name"]))
        summary = html.escape(str(branch["summary"]))
        count = int(branch["condition_count"])
        state = "启用" if branch["enabled"] else "停用"
        items.append(
            f'<button type="button" class="vs-branch-summary{css}" '
            f'data-vs-branch-id="{html.escape(str(branch["branch_id"]), quote=True)}" '
            f'data-vs-branch-index="{index - 1}" '
            f'aria-pressed="{str(active).lower()}" '
            f'aria-label="切换到分支：{name}"><b>分支 {index} · {name}</b>'
            f'<span>{count} 个条件 · {state}</span><p>{summary}</p></button>'
        )
    return '<section class="vs-branch-grid">' + "".join(items) + "</section>"


def render_parameter_help(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "选择一条业务条件后，这里会显示可修改参数和作用说明。"
    return "\n".join(
        f"- **{row['name']}**：{row['help']}"
        + (f"（单位：{row['unit']}）" if row["unit"] else "")
        for row in rows
    )


__all__ = [
    "display_value",
    "parameter_table_rows",
    "parse_display_value",
    "parse_parameter_table",
    "render_branch_overview",
    "render_branch_pattern",
    "render_condition_tree",
    "render_parameter_help",
]
