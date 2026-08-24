from __future__ import annotations

from pathlib import Path

from core.document_hashes import refresh_document_hashes
from core.editor_migrations import migrate_editor_document, migration_report
from core.legacy_importer import import_skill_package
from core.schema import SkillPackage


def _legacy_document():
    package = SkillPackage.model_validate_json(
        next(Path("presets_v2").glob("P05*.json")).read_text("utf-8")
    )
    return import_skill_package(package)


def test_3_0_to_3_2_migration_is_explicit_complete_and_idempotent():
    legacy = _legacy_document()
    assert legacy.schema_version == "3.0"

    migrated = migrate_editor_document(legacy)
    again = migrate_editor_document(migrated)

    assert migrated.schema_version == "3.2"
    assert migrated.model_dump(mode="json") == again.model_dump(mode="json")
    assert migrated.skill_template.final_decision is not None
    assert all(item.source_ref for item in migrated.skill_template.result_specs)
    assert {
        item.result_id for item in migrated.skill_template.result_specs
    } == {
        item.result_id for item in migrated.skill_template.presentation_specs
    }
    assert migrated.hashes.semantic_hash
    assert migrated.hashes.compile_hash
    assert migrated.hashes.package_hash
    assert migrated.hashes.presentation_hash
    assert migration_report(legacy)["changed"]


def test_presentation_change_does_not_invalidate_semantics_or_package():
    document = migrate_editor_document(_legacy_document())
    before = document.hashes
    presentations = [
        item.model_copy(update={"precision": 3, "display_order": index + 10})
        for index, item in enumerate(document.skill_template.presentation_specs)
    ]
    template = document.skill_template.model_copy(
        update={"presentation_specs": presentations}
    )
    updated = refresh_document_hashes(
        document.model_copy(update={"skill_template": template})
    )

    assert updated.hashes.presentation_hash != before.presentation_hash
    assert updated.hashes.semantic_hash == before.semantic_hash
    assert updated.hashes.compile_hash == before.compile_hash
    assert updated.hashes.package_hash == before.package_hash


def test_result_semantic_change_invalidates_semantic_and_compile_hashes():
    document = migrate_editor_document(_legacy_document())
    before = document.hashes
    specs = list(document.skill_template.result_specs)
    specs[0] = specs[0].model_copy(
        update={"projection": specs[0].projection.model_copy(update={"kind": "count"})}
    )
    template = document.skill_template.model_copy(update={"result_specs": specs})
    updated = refresh_document_hashes(
        document.model_copy(update={"skill_template": template})
    )

    assert updated.hashes.semantic_hash != before.semantic_hash
    assert updated.hashes.compile_hash != before.compile_hash
    assert updated.hashes.package_hash == before.package_hash
    assert updated.hashes.presentation_hash == before.presentation_hash
