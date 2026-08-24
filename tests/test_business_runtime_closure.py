from __future__ import annotations

import json

from PIL import Image

from core.business_capabilities import build_business_capability_registry
from core.business_rule_editor import BusinessRuleEditor
from core.editor_migrations import migrate_editor_document
from core.editor_schema import BusinessBranch, RuleGraph
from core.editor_service import EditorService
from core.legacy_importer import import_skill_package
from core.persistence import RunStore
from core.registry import build_default_registry
from core.runtime import SkillPackageRuntime
from core.schema import CanonicalSemanticIR
from core.semantic import WorkflowCompiler


class OnePersonRex:
    def detect(self, image, phrases):
        return [{"phrase": phrases[0], "bbox": [0.1, 0.2, 0.5, 0.8]}]


def _compiled_document():
    registry = build_default_registry()
    semantic = CanonicalSemanticIR.model_validate(
        {
            "mode": "direct_grounding",
            "target": {
                "concept": "person",
                "source_span": "人员",
                "phrases": ["person"],
            },
            "constraints": [],
            "logic": "all",
            "unresolved": [],
            "semantic_hash": "d" * 64,
        }
    )
    package = WorkflowCompiler(registry).compile(
        semantic,
        original_instruction="画出人员框、统计人数，大于0则告警",
        requested_accept=["image"],
        skill_id="business_runtime_closure",
        display_name="人员数量告警",
    )
    document = migrate_editor_document(import_skill_package(package))
    document.skill_template.rule_graph = RuleGraph()
    document.skill_template.rule_graphs = {"image": RuleGraph()}
    document.skill_template.business_branches = [
        BusinessBranch(
            branch_id="branch_people",
            display_name="画面内有人",
            media_type="image",
        )
    ]
    document.skill_template.event_patterns = []
    document.skill_template.result_specs = []
    document.skill_template.presentation_specs = []
    document.skill_template.final_decision = None
    document.effective_skill_package = None
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    document, people_id = editor.add_condition(
        document, "branch_people", "target.detect"
    )
    document = editor.update_condition(
        document,
        "branch_people",
        people_id,
        display_name="检测人员",
        parameters={
            "targets": ["person"],
            "phrases": "person",
            "business_label": "人员",
        },
    )
    document, count_id = editor.add_condition(
        document, "branch_people", "measure.count"
    )
    document = editor.update_condition(
        document,
        "branch_people",
        count_id,
        display_name="人数大于0",
        parameters={
            "source": f"condition:{people_id}",
            "scope": "full_frame",
            "group_by": "total",
            "operator": ">",
            "threshold": 0,
        },
    )
    document = editor.set_final_decision(
        document,
        "人员数量告警",
        "event_decision",
        "branch:branch_people",
    )
    document = editor.set_trigger_policy(
        document,
        mode="once",
        cooldown_seconds=0,
        severity="medium",
        outputs=["event_record", "annotated_media"],
    )
    document = editor.set_result_rows(
        document,
        [
            {
                "display_name": "人员框",
                "source_ref": f"condition:{people_id}",
                "result_kind": "entities",
                "evidence_policy": "required",
            },
            {
                "display_name": "实际人数",
                "source_ref": f"condition:{count_id}",
                "result_kind": "count",
                "unit": "人",
                "evidence_policy": "required",
            },
            {
                "display_name": "人员数量告警",
                "source_ref": "final:primary",
                "result_kind": "decision",
                "evidence_policy": "required",
            },
        ],
    )
    return registry, EditorService(registry).apply(document)


def test_business_rule_executes_to_final_outputs_boxes_and_traceable_evidence(tmp_path):
    registry, document = _compiled_document()
    package = document.effective_skill_package
    media = tmp_path / "people.jpg"
    Image.new("RGB", (100, 60), "white").save(media)

    record = SkillPackageRuntime(
        registry,
        rex=OnePersonRex(),
        run_store=RunStore(tmp_path / "runs"),
    ).run(package, package, media, editor_document=document)

    result = json.loads((record.run_dir / "run_result_v3.json").read_text("utf-8"))
    outputs = {item["display_name"]: item for item in result["business_outputs"]}
    assert result["final_result"]["status"] == "satisfied"
    assert result["final_result"]["reason"] == "事件已发生"
    assert result["branch_results"][0]["status"] == "satisfied"
    assert len(outputs["人员框"]["value"]) == 1
    assert outputs["人员框"]["value"][0]["business_label"] == "人员"
    assert outputs["人员框"]["value"][0]["model_label"] == "person"
    assert outputs["实际人数"]["value"] == 1
    assert outputs["实际人数"]["unit"] == "人"
    assert outputs["人员数量告警"]["value"] is True
    assert all(item["source_value_refs"] for item in outputs.values())
    assert all(item["evidence_refs"] for item in outputs.values())

    runtime_values = json.loads(
        (record.run_dir / "runtime_values.json").read_text("utf-8")
    )
    source_refs = {item["business_source_ref"] for item in runtime_values}
    assert any(item.startswith("condition:") for item in source_refs)
    assert "branch:branch_people" in source_refs
    assert "final:primary" in source_refs
    assert any(item.startswith("result:") for item in source_refs)

    evidence = json.loads(
        (record.run_dir / "evidence" / "index.json").read_text("utf-8")
    )
    assert any(item["evidence_type"] == "box" for item in evidence["records"])
    assert record.annotated_media is not None
    assert record.annotated_media.is_file()
