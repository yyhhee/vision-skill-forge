from __future__ import annotations

import json
from pathlib import Path

from core.business_capabilities import build_business_capability_registry
from core.business_rule_editor import BusinessRuleEditor
from core.editor_generation import build_editor_document
from core.editor_migrations import migrate_editor_document
from core.editor_service import EditorService
from core.registry import build_default_registry
from core.schema import SkillPackage


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "v3" / "preset_reproduction_manifest.json"


def _cases():
    data = json.loads(MANIFEST.read_text("utf-8"))
    assert data["schema_version"] == "1.0"
    return data["cases"]


def test_reproduction_manifest_covers_p01_to_p13_and_two_natural_language_styles():
    cases = _cases()
    assert [item["preset_id"] for item in cases] == [f"P{index:02d}" for index in range(1, 14)]
    for item in cases:
        assert item["free_text"].strip()
        assert "条件分支" in item["structured_text"]
        assert "最终判定" in item["structured_text"]
        assert "业务输出" in item["structured_text"]


def test_generated_condition_rows_expose_capability_ids_like_imported_rows():
    registry = build_default_registry()
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    package = SkillPackage.model_validate_json(
        (ROOT / "presets_v2" / "P01_fire_smoke.json").read_text("utf-8")
    )
    document = editor.prepare(build_editor_document(package, source_type="preset"))
    branch = document.skill_template.business_branches[0]
    rows = editor.condition_rows(document, branch.branch_id)
    assert all(
        "capability_id" in row
        for row in rows
        if row["kind"] in {"条件", "导入判定"}
    )


def test_every_manifest_case_loads_into_the_same_editable_business_editor_and_recompiles():
    registry = build_default_registry()
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    service = EditorService(registry)

    for case in _cases():
        package = SkillPackage.model_validate_json(
            (ROOT / "presets_v2" / case["package"]).read_text("utf-8")
        )
        assert list(package.input.accept) == case["media"]
        document_path = (
            ROOT / "presets_v2" / "editor_documents" / case["package"]
        )
        document = (
            migrate_editor_document(json.loads(document_path.read_text("utf-8")))
            if document_path.is_file()
            else build_editor_document(package, source_type="preset")
        )
        document.effective_skill_package = package
        document = editor.prepare(document)
        visible_capabilities = set()
        for branch in document.skill_template.business_branches:
            visible_capabilities.update(
                row.get("capability_id")
                for row in editor.condition_rows(document, branch.branch_id)
                if row.get("capability_id")
            )
        assert set(case["editor_capabilities"]) <= visible_capabilities

        compiled = service.apply(document)
        assert compiled.effective_skill_package is not None
        assert set(compiled.effective_skill_package.variants) == set(case["media"])
        assert compiled.skill_template.final_decision is not None
        assert set(compiled.skill_template.final_decision.media_source_refs) == set(case["media"])


def test_all_frozen_successful_historical_cases_migrate_and_recompile_without_losing_semantics():
    artifact = json.loads(
        (
            ROOT
            / "tests"
            / "historical_v2_acceptance_consolidated_20260814.json"
        ).read_text("utf-8")
    )
    assert artifact["case_count"] == 10
    assert all(item["status"] == "automatic_passed" for item in artifact["cases"])
    registry = build_default_registry()
    editor = BusinessRuleEditor(
        build_business_capability_registry(registry), registry
    )
    service = EditorService(registry)

    for case in artifact["cases"]:
        package = SkillPackage.model_validate(case["package"])
        document = editor.prepare(
            build_editor_document(package, source_type="legacy")
        )
        assert document.skill_template.semantic_ir.semantic_hash == package.semantic_ir.semantic_hash
        assert document.skill_template.business_branches
        assert all(
            editor.condition_rows(document, branch.branch_id)
            for branch in document.skill_template.business_branches
        )
        compiled = service.apply(document)
        assert compiled.effective_skill_package is not None
        assert compiled.effective_skill_package.semantic_ir.semantic_hash == package.semantic_ir.semantic_hash
        for media_type, original in package.variants.items():
            original_ids = {node.id for node in original.nodes if node.enabled}
            actual_ids = {
                node.id
                for node in compiled.effective_skill_package.variants[media_type].nodes
            }
            assert original_ids <= actual_ids
