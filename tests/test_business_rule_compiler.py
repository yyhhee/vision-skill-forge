from __future__ import annotations

from core.business_capabilities import build_business_capability_registry
from core.business_result_projector import build_runtime_contract
from core.business_rule_editor import BusinessRuleEditor
from core.editor_migrations import migrate_editor_document
from core.editor_schema import (
    BusinessBranch,
    CardinalitySpec,
    ResolvableValue,
    ResourceRequirement,
    RuleGraph,
    TemporalQualifierSpec,
)
from core.editor_service import EditorService
from core.legacy_importer import import_skill_package
from core.registry import build_default_registry
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler


def _document(media_type: str):
    registry = build_default_registry()
    semantic = CanonicalSemanticIR.model_validate(
        {
            "schema_version": "1.0",
            "mode": "direct_grounding",
            "target": {
                "concept": "person",
                "source_span": "人",
                "phrases": ["person"],
            },
            "constraints": [],
            "logic": "all",
            "unresolved": [],
            "semantic_hash": "b" * 64,
        }
    )
    package = WorkflowCompiler(registry).compile(
        semantic,
        original_instruction="业务规则编译测试",
        requested_accept=[media_type],
        skill_id="business_rule_compile_fixture",
        display_name="业务规则编译测试",
    )
    document = migrate_editor_document(import_skill_package(package))
    graph = RuleGraph()
    document.skill_template.rule_graph = graph
    document.skill_template.rule_graphs = {media_type: graph}
    document.skill_template.business_branches = []
    document.skill_template.event_patterns = []
    document.skill_template.result_specs = []
    document.skill_template.presentation_specs = []
    document.skill_template.final_decision = None
    document.effective_skill_package = None
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    return registry, editor, document


def _condition(
    editor: BusinessRuleEditor,
    document,
    branch_id: str,
    capability: str,
    name: str,
    parameters: dict,
):
    document, condition_id = editor.add_condition(
        document, branch_id, capability
    )
    document = editor.update_condition(
        document,
        branch_id,
        condition_id,
        display_name=name,
        parameters=parameters,
    )
    return document, condition_id


def test_image_business_tree_compiles_to_atomic_graph_and_semantic_outputs():
    registry, editor, document = _document("image")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_clothes",
            display_name="区域1指定着装人员",
            media_type="image",
        ),
        BusinessBranch(
            branch_id="branch_count",
            display_name="区域2人员数量",
            media_type="image",
        ),
    ]
    document, people_id = _condition(
        editor,
        document,
        "branch_clothes",
        "target.detect",
        "检测人员",
        {"targets": ["person"], "phrases": "person", "business_label": "人员"},
    )
    document, red_id = _condition(
        editor,
        document,
        "branch_clothes",
        "attribute.color",
        "红色上衣",
        {
            "source": f"condition:{people_id}",
            "part": "upper_clothing",
            "color": "red",
            "minimum_fraction": 20,
        },
    )
    document, gray_id = _condition(
        editor,
        document,
        "branch_clothes",
        "attribute.color",
        "灰色裤子",
        {
            "source": f"condition:{people_id}",
            "part": "lower_clothing",
            "color": "gray",
            "minimum_fraction": 20,
        },
    )
    document, same_id = _condition(
        editor,
        document,
        "branch_clothes",
        "subject.same_attributes",
        "同一人员同时满足着装",
        {
            "subject": f"condition:{people_id}",
            "attributes": [f"condition:{red_id}", f"condition:{gray_id}"],
            "minimum_overlap": 30,
        },
    )
    document, people_2_id = _condition(
        editor,
        document,
        "branch_count",
        "target.detect",
        "区域2人员",
        {"targets": ["person"], "phrases": "person", "business_label": "人员"},
    )
    document, count_id = _condition(
        editor,
        document,
        "branch_count",
        "measure.count",
        "区域2人数大于2",
        {
            "source": f"condition:{people_2_id}",
            "scope": "full_frame",
            "group_by": "total",
            "operator": ">",
            "threshold": 2,
        },
    )
    document = editor.set_final_decision(
        document,
        "多区域人员告警",
        "event_decision",
        "branch:branch_clothes",
        source_refs=["branch:branch_clothes", "branch:branch_count"],
        combination="AND",
    )
    document = editor.set_trigger_policy(
        document,
        mode="once",
        cooldown_seconds=30,
        severity="high",
        outputs=["event_record", "annotated_media"],
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "红色上衣、灰色裤子人员",
                "source_ref": f"condition:{same_id}",
                "result_kind": "entities",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
            {
                "display_name": "区域2人员数量",
                "source_ref": f"condition:{count_id}",
                "result_kind": "count",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
            {
                "display_name": "多区域人员告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            },
        ],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["image"]
    operators = {item.op for item in variant.nodes}

    assert compiled.validation_report["can_run"] is True
    assert "set.semi_join@1.0" in operators
    assert "measure.count@1.0" in operators
    assert "logic.all@1.0" in operators
    assert "final_primary" in variant.outputs
    assert "alert_primary" in variant.outputs
    assert "event.trigger@2.0" in operators
    assert "output.draw@1.0" in operators
    assert "media" in variant.outputs
    assert all(item.required_outputs for item in compiled.skill_template.result_specs)

    contract = build_runtime_contract(compiled, "image")
    sources = contract["published_sources"]
    count_result = next(
        item
        for item in compiled.skill_template.result_specs
        if item.display_name == "区域2人员数量"
    )
    assert f"condition:{count_id}" in sources
    assert "branch:branch_count" in sources
    assert "final:primary" in sources
    assert f"result:{count_result.result_id}" in sources
    # The condition remains boolean while its ResultSpec binds to the
    # measurement node selected by the count projection.
    assert sources[f"condition:{count_id}"] != sources[f"result:{count_result.result_id}"]


def test_video_branch_qualifier_keeps_frames_and_requires_direction_resource():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_wrong_way",
            display_name="车辆逆行",
            media_type="video",
        )
    ]
    document.skill_template.resource_requirements = [
        ResourceRequirement(
            requirement_id="normal_direction",
            resource_type="direction_collection",
            display_name="正常行驶方向",
            semantic_role="normal_direction",
            cardinality=CardinalitySpec(mode="dynamic", minimum=1),
            required_before="run",
            media_types=["video"],
        )
    ]
    document, vehicles_id = _condition(
        editor,
        document,
        "branch_wrong_way",
        "target.detect",
        "检测车辆",
        {"targets": ["vehicle"], "phrases": "vehicle", "business_label": "车辆"},
    )
    document, _ = _condition(
        editor,
        document,
        "branch_wrong_way",
        "motion.wrong_way",
        "车辆逆行",
        {
            "source": f"condition:{vehicles_id}",
            "scope": "full_frame",
            "reference": "normal_direction",
            "minimum_reverse_angle": 120,
            "minimum_displacement": 2,
        },
    )
    branch = document.skill_template.business_branches[0]
    branch.temporal_qualifiers = [
        TemporalQualifierSpec(
            qualifier_id="wrong_way_3s",
            display_name="同一车辆持续逆行3秒",
            target_ref="branch:branch_wrong_way",
            mode="continuous",
            duration_seconds=ResolvableValue(
                state="explicit", value=3.0, source="user"
            ),
            allowed_gap_seconds=0.5,
            identity_scope="track",
        )
    ]
    document = editor.set_final_decision(
        document,
        "逆行告警",
        "event_decision",
        "branch:branch_wrong_way",
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "逆行告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            }
        ],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["video"]

    assert compiled.validation_report["can_run"] is False
    assert compiled.validation_report["resource_blockers"] == ["normal_direction"]
    assert any(item.op == "track.iou@1.0" for item in variant.nodes)
    qualifier = next(item for item in variant.nodes if item.op == "temporal.qualify@1.0")
    assert qualifier.params["duration_seconds"] == 3.0
    assert any(slot.slot_id == "slot_normal_direction" for slot in variant.configuration_slots)


def test_complex_pattern_can_be_the_final_semantic_source():
    registry, editor, document = _document("video")
    document.skill_template.business_branches = [
        BusinessBranch(branch_id="branch_accident", display_name="交通事故", media_type="video"),
        BusinessBranch(branch_id="branch_fire", display_name="烟火爆炸", media_type="video"),
    ]
    for branch_id, label in (
        ("branch_accident", "traffic accident"),
        ("branch_fire", "fire and explosion"),
    ):
        document, _ = _condition(
            editor,
            document,
            branch_id,
            "target.detect",
            label,
            {"targets": [label], "phrases": label, "business_label": label},
        )
    document = editor.set_complex_pattern(
        document,
        "video",
        "sequence",
        ["branch_accident", "branch_fire"],
        window_seconds=30,
        display_name="事故后发生烟火爆炸",
    )
    pattern_id = document.skill_template.event_patterns[0].pattern_id
    document = editor.set_final_decision(
        document,
        "事故后烟火爆炸告警",
        "timeline_summary",
        f"event:{pattern_id}",
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "事故后烟火爆炸告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
                "save_policy": "always",
                "show_in_overview": True,
            }
        ],
    )

    compiled = EditorService(registry).apply(document)
    variant = compiled.effective_skill_package.variants["video"]
    assert any(item.op == "temporal.sequence@2.0" for item in variant.nodes)
    assert variant.outputs["final_primary"].startswith("$pattern_")
    contract = build_runtime_contract(compiled, "video")
    assert f"event:{pattern_id}" in contract["published_sources"]
    assert "final:primary" in contract["published_sources"]
