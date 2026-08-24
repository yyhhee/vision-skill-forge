from __future__ import annotations

import html
import json
from typing import Any


def display_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


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
    cards = []
    for row in rows:
        depth = min(int(row.get("depth", 0)), 6)
        name = html.escape(str(row.get("name") or "未命名条件"))
        summary = html.escape(str(row.get("summary") or ""))
        category = html.escape(str(row.get("category") or ""))
        status = html.escape(str(row.get("status") or ""))
        logic = str(row.get("logic") or "")
        relation = ""
        if row.get("kind") == "条件组":
            relation = f'<span class="vs-logic-badge">{html.escape(logic)}</span>'
        state_class = "is-ready" if status in {"已配置", "可用"} else "is-pending"
        if status == "已停用":
            state_class = "is-disabled"
        cards.append(
            f'<article class="vs-rule-node {state_class}" style="--rule-depth:{depth}">'
            f'<div class="vs-rule-node-head"><span class="vs-rule-category">{category}</span>{relation}'
            f'<span class="vs-rule-status">{status}</span></div>'
            f'<strong>{name}</strong><p>{summary}</p></article>'
        )
    return '<section class="vs-rule-tree">' + "".join(cards) + "</section>"


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
            f'<article class="vs-branch-summary{css}"><b>分支 {index} · {name}</b>'
            f'<span>{count} 个条件 · {state}</span><p>{summary}</p></article>'
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
    "render_condition_tree",
    "render_parameter_help",
]
