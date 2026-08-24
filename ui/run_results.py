from __future__ import annotations

import html
import json
from typing import Any

from core.run_result_view import RunResultViewModel


_STATUS_LABELS = {
    "satisfied": "已满足",
    "not_satisfied": "未满足",
    "pending": "等待中",
    "not_evaluable": "无法判断",
    "error": "运行错误",
}


def _safe(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _value_text(value: Any, unit: str | None = None) -> str:
    if isinstance(value, (dict, list)):
        if isinstance(value, list):
            return f"{len(value)} 条"
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return "—"
    return f"{value}{unit or ''}"


def render_run_result_html(view: RunResultViewModel) -> str:
    final = view.final_result
    final_status = _STATUS_LABELS.get(final.get("status"), final.get("status", "未知"))
    final_value = _value_text(final.get("value"))
    output_cards = "".join(
        (
            '<article class="vs-result-card" tabindex="0">'
            f'<div class="vs-result-card-title">{_safe(card.title)}</div>'
            f'<div class="vs-result-card-value">{_safe(_value_text(card.value, card.unit))}</div>'
            f'<div class="vs-result-card-status">{_safe(_STATUS_LABELS.get(card.status, card.status))}</div>'
            f'<p>{_safe(card.reason or "")}</p>'
            f'<small>证据 {len(card.evidence_refs)} 条 · {_safe(card.renderer_id)}</small>'
            "</article>"
        )
        for card in view.business_outputs
    ) or '<p class="vs-empty-result">当前技能没有额外业务输出。</p>'
    branch_cards = "".join(
        (
            '<details class="vs-branch-card">'
            f'<summary>{_safe(branch.title)} · {_safe(_STATUS_LABELS.get(branch.status, branch.status))}</summary>'
            f'<p>{_safe(branch.reason or "")}</p>'
            f'<p>证据 {len(branch.evidence_refs)} 条</p>'
            "</details>"
        )
        for branch in view.branch_results
    ) or '<p class="vs-empty-result">当前技能没有独立分支过程。</p>'
    return (
        '<section class="vs-business-results" aria-label="运行结果">'
        '<nav class="vs-result-nav">最终结果 ｜ 业务输出 ｜ 分支与证据</nav>'
        '<section class="vs-final-result" aria-labelledby="vs-final-title">'
        '<h3 id="vs-final-title">最终结果</h3>'
        f'<div class="vs-final-status">{_safe(final_status)}</div>'
        f'<h2>{_safe(final.get("display_name", "最终结果"))}</h2>'
        f'<div class="vs-final-value">{_safe(final_value)}</div>'
        f'<p>{_safe(final.get("reason", ""))}</p>'
        "</section>"
        '<section class="vs-business-output-layer"><h3>业务输出</h3>'
        f'<div class="vs-result-grid">{output_cards}</div></section>'
        '<section class="vs-evidence-layer"><h3>分支与证据</h3>'
        f'{branch_cards}<p>本次可定位证据共 {len(view.evidence_refs)} 条；点击具体结果后查看媒体位置与详情。</p>'
        "</section></section>"
    )


__all__ = ["render_run_result_html"]
