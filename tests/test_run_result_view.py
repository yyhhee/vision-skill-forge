from __future__ import annotations

from core.business_result_schema import BusinessOutputValue, FinalResult, RunResult
from core.result_presentation_schema import PresentationSpec
from core.run_result_view import build_run_result_view
from ui.run_results import render_run_result_html


def _run_result():
    return RunResult(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="image",
        variant="image",
        final_result=FinalResult(
            decision_id="primary",
            display_name="多区域人员告警",
            decision_type="event_decision",
            status="satisfied",
            value=True,
            reason="事件已发生",
            source_ref="result:alert",
            evidence_refs=["ev_1"],
        ),
        business_outputs=[
            BusinessOutputValue(
                result_id="people_count",
                display_name="区域2人数",
                semantic_type="scalar",
                value_shape="single",
                status="satisfied",
                value=3,
                unit="人",
                reason="结果已计算",
                source_ref="output:people",
                evidence_refs=["ev_2"],
            )
        ],
    )


def test_run_result_view_uses_semantic_renderer_and_three_layer_html():
    view = build_run_result_view(
        _run_result(),
        [
            PresentationSpec(
                result_id="people_count",
                preferred_renderer="scalar.metric",
                display_order=1,
            )
        ],
    )
    rendered = render_run_result_html(view)

    assert view.business_outputs[0].renderer_id == "scalar.metric"
    assert "最终结果" in rendered
    assert "业务输出" in rendered
    assert "分支与证据" in rendered
    assert "多区域人员告警" in rendered
    assert "区域2人数" in rendered


def test_unknown_or_incompatible_renderer_safely_falls_back():
    view = build_run_result_view(
        _run_result(),
        [
            PresentationSpec(
                result_id="people_count",
                preferred_renderer="event.list",
            )
        ],
    )
    assert view.business_outputs[0].renderer_id == "scalar.metric"
