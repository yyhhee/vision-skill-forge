from __future__ import annotations

import pytest

from core.business_result_projector import project_run_result
from core.editor_schema import BusinessBranch, FinalDecisionSpec, ResultSpec
from core.runtime_values import RuntimeValueEnvelope


def _envelope(
    source_ref: str,
    value,
    value_type="entity_set",
    *,
    value_id: str = "value_1",
    status: str = "available",
):
    return RuntimeValueEnvelope(
        value_id=value_id,
        run_id="run_1",
        source_node_id="node_1",
        business_source_ref=source_ref,
        value_type=value_type,
        value_shape="list",
        value=value,
        evidence_refs=["ev_1"],
        status=status,
    )


def test_semantic_result_projection_builds_business_output_and_final_result():
    spec = ResultSpec(
        result_id="people_count",
        display_name="区域2人数",
        semantic_type="scalar",
        value_shape="single",
        source_ref="output:people",
        projection={"kind": "count"},
        unit="人",
        result_type="count",
        required_outputs=["people"],
    )
    result = project_run_result(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="image",
        result_specs=[spec],
        final_decision=FinalDecisionSpec(
            display_name="人数条件",
            decision_type="measurement_decision",
            source_ref="result:people_count",
            success_condition={"operator": ">", "value": 2},
        ),
        branches=[],
        envelopes=[
            _envelope(
                "output:people",
                {"items": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]},
            )
        ],
    )

    assert result.business_outputs[0].value == 3
    assert result.business_outputs[0].evidence_refs == ["ev_1"]
    assert result.final_result.status == "satisfied"
    assert result.final_result.reason == "实际值满足要求"


def test_missing_result_source_is_not_evaluable_instead_of_guessing_by_name():
    spec = ResultSpec(
        result_id="accident",
        display_name="交通事故",
        semantic_type="event_set",
        value_shape="list",
        source_ref="output:accident_events",
        projection={"kind": "events"},
        result_type="event",
    )
    result = project_run_result(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="video",
        result_specs=[spec],
        final_decision=FinalDecisionSpec(
            display_name="事故告警",
            decision_type="event_decision",
            source_ref="result:accident",
        ),
        branches=[],
        envelopes=[_envelope("output:other_events", {"items": []}, "event_set")],
    )

    assert result.business_outputs[0].status == "not_evaluable"
    assert result.final_result.status == "not_evaluable"
    assert "accident_events" in result.business_outputs[0].reason


@pytest.mark.parametrize(
    ("combination", "required_count", "expected"),
    [
        ("AND", None, "not_satisfied"),
        ("OR", None, "satisfied"),
        ("N_OF_M", 2, "not_satisfied"),
    ],
)
def test_final_decision_combines_stable_branch_sources(
    combination, required_count, expected
):
    decision = FinalDecisionSpec(
        display_name="多分支判定",
        decision_type="event_decision",
        source_ref="branch:a",
        source_refs=["branch:a", "branch:b"],
        combination=combination,
        required_count=required_count,
    )
    result = project_run_result(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="video",
        result_specs=[],
        final_decision=decision,
        branches=[
            BusinessBranch(branch_id="a", display_name="分支A", media_type="video"),
            BusinessBranch(branch_id="b", display_name="分支B", media_type="video"),
        ],
        envelopes=[
            _envelope(
                "branch:a",
                {"items": [{"timestamp": 0, "value": True}]},
                "boolean",
                value_id="value_a",
            ),
            _envelope(
                "branch:b",
                {"items": [{"timestamp": 0, "value": False}]},
                "boolean",
                value_id="value_b",
            ),
        ],
    )

    assert result.final_result.status == expected
    assert result.final_result.source_value_refs == ["value_a", "value_b"]
    assert result.final_result.value["combination"] == combination


def test_final_decision_distinguishes_pending_missing_and_false_sources():
    decision = FinalDecisionSpec(
        display_name="全部分支",
        decision_type="event_decision",
        source_ref="branch:a",
        source_refs=["branch:a", "branch:b"],
        combination="AND",
    )
    branches = [
        BusinessBranch(branch_id="a", display_name="分支A", media_type="video"),
        BusinessBranch(branch_id="b", display_name="分支B", media_type="video"),
    ]
    pending = project_run_result(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="video",
        result_specs=[],
        final_decision=decision,
        branches=branches,
        envelopes=[
            _envelope(
                "branch:a",
                {"items": [{"timestamp": 0, "value": True}]},
                "boolean",
                status="pending",
            )
        ],
    )
    false_result = project_run_result(
        run_id="run_2",
        media_asset_id="media_1",
        media_type="video",
        result_specs=[],
        final_decision=decision,
        branches=branches,
        envelopes=[
            _envelope(
                "branch:a",
                {"items": [{"timestamp": 0, "value": False}]},
                "boolean",
            )
        ],
    )

    assert pending.final_result.status == "pending"
    assert pending.branch_results[0].status == "pending"
    assert pending.branch_results[1].status == "not_evaluable"
    assert false_result.final_result.status == "not_satisfied"


def test_final_result_spec_projects_compiled_final_source_before_rendering():
    spec = ResultSpec(
        result_id="alert",
        display_name="多区域人员告警",
        semantic_type="decision",
        value_shape="single",
        source_ref="final:primary",
        projection={"kind": "status"},
        empty_policy="not_satisfied",
    )
    result = project_run_result(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="image",
        result_specs=[spec],
        final_decision=FinalDecisionSpec(
            display_name="多区域人员告警",
            decision_type="event_decision",
            source_ref="result:alert",
        ),
        branches=[],
        envelopes=[
            _envelope(
                "final:primary",
                {"items": [{"timestamp": 0, "value": True}]},
                "boolean",
            )
        ],
    )

    assert result.business_outputs[0].status == "satisfied"
    assert result.business_outputs[0].value is True
    assert result.final_result.status == "satisfied"


def test_result_spec_rejects_semantic_projection_mismatch_before_renderer_selection():
    with pytest.raises(ValueError, match="内容类型与取值方式不一致"):
        ResultSpec(
            result_id="bad_boxes",
            display_name="人员框",
            semantic_type="entity_set",
            value_shape="list",
            source_ref="output:people",
            projection={"kind": "count"},
        )

    with pytest.raises(ValueError, match="内容类型与结果结构不一致"):
        ResultSpec(
            result_id="bad_media",
            display_name="标注媒体",
            semantic_type="media",
            value_shape="list",
            source_ref="output:media",
            projection={"kind": "media"},
        )


def test_runtime_source_type_is_checked_before_semantic_projection():
    spec = ResultSpec(
        result_id="people_boxes",
        display_name="人员框",
        semantic_type="entity_set",
        value_shape="list",
        source_ref="output:people",
        projection={"kind": "entities"},
    )
    result = project_run_result(
        run_id="run_1",
        media_asset_id="media_1",
        media_type="image",
        result_specs=[spec],
        final_decision=FinalDecisionSpec(
            display_name="人员检测",
            decision_type="detection_summary",
            source_ref="result:people_boxes",
        ),
        branches=[],
        envelopes=[
            _envelope(
                "output:people",
                {"items": [{"timestamp": 0, "value": 3}]},
                "scalar",
            )
        ],
    )

    assert result.business_outputs[0].status == "not_evaluable"
    assert "实际内容类型" in result.business_outputs[0].reason
    assert result.final_result.status == "not_evaluable"
