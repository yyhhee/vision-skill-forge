from __future__ import annotations

from pathlib import Path

from core.editor_generation import build_editor_document
from core.effective_package_view import build_effective_package_view
from core.schema import SkillPackage


def test_effective_package_view_is_read_only_auditable_and_hash_matched():
    package = SkillPackage.model_validate_json(
        next(Path("presets_v2").glob("P05*.json")).read_text("utf-8")
    )
    document = build_editor_document(package, source_type="preset")
    view = build_effective_package_view(package, document)

    assert view["package_hash_matches_document"] is True
    assert view["hashes"]["package_hash"] == document.hashes.package_hash
    assert view["variants"]
    assert view["effective_skill_package"]["skill_id"] == package.skill_id
