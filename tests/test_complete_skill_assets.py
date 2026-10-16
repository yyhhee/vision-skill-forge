"""Complete editor/runtime asset round trips, legacy compatibility and safety."""

from __future__ import annotations

import json

import gradio as gr
import pytest
from test_generic_editor_ui import _controller, _package
from test_pattern_group_editor import _groups

from application.v2.support import ApplicationError
from core.document_hashes import compute_document_hashes
from core.editor_schema import ResourceCollection, ResourceInstance, SceneProfile
from core.persistence import PackageStore, SkillDocumentStore
from core.schema import SkillPackage


def _complete(tmp_path):
    c = _controller(tmp_path)
    _, e, d, child, parent = _groups()
    d = e.set_branch_time_policy(
        d, "a", mode="continuous", duration_seconds=2, identity_scope="global"
    )
    d = e.set_trigger_policy(
        d,
        mode="on_change",
        cooldown_seconds=4,
        severity="high",
        outputs=["event_record", "annotated_media"],
    )
    d.scene_profiles = [
        SceneProfile(
            display_name="现场标注",
            media_fingerprint="scene-fixture",
            collections=[
                ResourceCollection(
                    requirement_id="manual_scene_region",
                    completed=True,
                    items=[
                        ResourceInstance(
                            resource_id="roi_1",
                            resource_type="region",
                            display_name="区域1",
                            semantic_role="区域",
                            geometry={
                                "shape": "rectangle",
                                "points": [[0.1, 0.2], [0.8, 0.9]],
                            },
                        )
                    ],
                )
            ],
        )
    ]
    d.active_scene_profile_id = d.scene_profiles[0].scene_profile_id
    d = c.configuration_service.publish(d)
    return c, d, child, parent


def _reload(c, selection, root=""):
    _, package, _, status, _ = c.load_saved_skill(selection, root)
    document = c._parse_editor_json(c.load_editor_configuration(package, "已保存技能"))
    return SkillPackage.model_validate_json(package), document, status


def test_complete_editor_document_survives_fresh_controller_roundtrip(tmp_path):
    c, d, child, parent = _complete(tmp_path)
    original = d.model_dump(mode="json")
    package = d.effective_skill_package
    c.save_skill_bundle(c._dump(package), c._dump(d))
    fresh = _controller(tmp_path)
    loaded_package, loaded, status = _reload(fresh, f"{package.skill_id}/v1")
    assert [p.pattern_id for p in loaded.skill_template.event_patterns] == [
        child,
        parent,
    ]
    assert loaded.skill_template.model_dump(mode="json") == d.skill_template.model_dump(
        mode="json"
    )
    assert loaded.scene_profiles == d.scene_profiles
    assert loaded.active_scene_profile_id == d.active_scene_profile_id
    assert loaded.user_overrides == d.user_overrides
    assert loaded.effective_skill_package == loaded_package
    assert loaded.hashes == compute_document_hashes(loaded)
    fresh.configuration_service.require_current(loaded, loaded_package)
    assert "完整编辑" in status
    assert d.model_dump(mode="json") == original
    assert (
        fresh.pattern_group_controls(fresh._dump(loaded), "video", child)[0] == "先A后B"
    )
    assert len(fresh.business_rule_editor.branch_rows(loaded, "video")) == 3


def test_renamed_bundle_and_repeated_versions_keep_pair_metadata_aligned(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    custom = tmp_path / "资产"
    for version in (1, 2):
        c.save_skill_bundle(
            c._dump(d.effective_skill_package),
            c._dump(d),
            "copied_skill",
            "复制的技能",
            str(custom),
        )
        loaded_package, loaded, _ = _reload(
            _controller(tmp_path), f"copied_skill/v{version}", str(custom)
        )
        assert loaded.version == loaded_package.version == version
        assert (
            loaded.skill_template.skill_id == loaded_package.skill_id == "copied_skill"
        )
        assert (
            loaded.skill_template.display_name
            == loaded_package.display_name
            == "复制的技能"
        )
        assert loaded.effective_skill_package == loaded_package
        assert loaded.skill_template.event_patterns == d.skill_template.event_patterns
        c.configuration_service.require_current(loaded, loaded_package)


def test_version_numbers_align_when_package_and_document_histories_diverge(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    p = d.effective_skill_package
    c.package_store.save(p)
    c.package_store.save(p)
    c.save_skill_bundle(c._dump(p), c._dump(d))
    _, loaded, _ = _reload(_controller(tmp_path), f"{p.skill_id}/v3")
    assert loaded.version == 3 and len(loaded.skill_template.event_patterns) == 2
    # A document-only prior attempt must not be overwritten either.
    c.document_store.save(d, skill_id="other")
    c.save_skill_bundle(c._dump(p), c._dump(d), "other")
    assert (c.document_store.root / "other" / "1.json").exists()
    assert (c.package_store.root / "other" / "2.json").exists()


def test_switching_saved_versions_with_same_identity_and_instruction_does_not_reuse_cache(
    tmp_path,
):
    c, d, child, _ = _complete(tmp_path)
    p = d.effective_skill_package
    c.save_skill_bundle(c._dump(p), c._dump(d))
    changed = d.model_copy(deep=True)
    changed.skill_template.event_patterns[0].display_name = "第二版组"
    changed = c.configuration_service.publish(changed)
    c.save_skill_bundle(c._dump(changed.effective_skill_package), c._dump(changed))
    _, version2, _ = _reload(c, f"{p.skill_id}/v2")
    _, version1, _ = _reload(c, f"{p.skill_id}/v1")
    assert (
        next(
            p for p in version2.skill_template.event_patterns if p.pattern_id == child
        ).display_name
        == "第二版组"
    )
    assert (
        next(
            p for p in version1.skill_template.event_patterns if p.pattern_id == child
        ).display_name
        == "先A后B"
    )


def test_package_only_legacy_load_remains_supported_and_explicit(tmp_path):
    c = _controller(tmp_path)
    p = _package()
    c.package_store.save(p)
    loaded_package, loaded, status = _reload(c, f"{p.skill_id}/v1")
    assert loaded.effective_skill_package == loaded_package
    assert "旧版本" in status and "运行包" in status
    c.configuration_service.require_current(loaded, loaded_package)


@pytest.mark.parametrize(
    "corruption",
    ["invalid_json", "wrong_skill", "wrong_version", "wrong_package", "dirty"],
)
def test_present_but_invalid_document_never_silently_falls_back(tmp_path, corruption):
    c, d, _, _ = _complete(tmp_path)
    p = d.effective_skill_package
    c.save_skill_bundle(c._dump(p), c._dump(d))
    path = c.document_store.root / p.skill_id / "1.json"
    raw = json.loads(path.read_text("utf-8"))
    if corruption == "invalid_json":
        path.write_text("{broken", encoding="utf-8")
    else:
        if corruption == "wrong_skill":
            raw["skill_template"]["skill_id"] = "wrong_skill"
        elif corruption == "wrong_version":
            raw["version"] = 99
        elif corruption == "wrong_package":
            raw["effective_skill_package"]["original_instruction"] = "wrong package"
        else:
            raw["validation_report"]["dirty"] = True
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    cached = c._generated_editor_documents.get(p.skill_id)
    with pytest.raises(gr.Error, match="编辑文档|不匹配|未应用"):
        c.load_saved_skill(f"{p.skill_id}/v1")
    assert c._generated_editor_documents.get(p.skill_id) is cached


def test_dirty_document_and_wrong_runtime_cannot_be_saved_as_clean_version(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    package = d.effective_skill_package
    dirty = d.model_copy(deep=True)
    dirty.skill_template.business_branches[0].display_name = "未应用修改"
    dirty = c.configuration_service.stage(d, dirty)
    with pytest.raises((gr.Error, ApplicationError), match="未应用|草稿"):
        c.save_skill_bundle(c._dump(package), c._dump(dirty))
    other = package.model_copy(update={"skill_id": "different_skill"})
    with pytest.raises((gr.Error, ApplicationError), match="同一个技能|不一致"):
        c.save_skill_bundle(c._dump(other), c._dump(d))
    assert c.package_store.list_versions() == []


def test_failed_document_write_does_not_publish_half_a_bundle(tmp_path, monkeypatch):
    c, d, _, _ = _complete(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("simulated document failure")

    monkeypatch.setattr(SkillDocumentStore, "save", fail)
    with pytest.raises(gr.Error, match="simulated"):
        c.save_skill_bundle(c._dump(d.effective_skill_package), c._dump(d))
    assert c.package_store.list_versions() == []


def test_package_write_failure_rolls_back_only_new_document_and_preserves_versions(
    tmp_path, monkeypatch
):
    c, d, _, _ = _complete(tmp_path)
    p = d.effective_skill_package
    c.save_skill_bundle(c._dump(p), c._dump(d))
    old_path = c.document_store.root / p.skill_id / "1.json"
    old_bytes = old_path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError("simulated package failure")

    monkeypatch.setattr(PackageStore, "save", fail)
    with pytest.raises(gr.Error, match="simulated"):
        c.save_skill_bundle(c._dump(p), c._dump(d))
    assert c.package_store.list_versions() == [f"{p.skill_id}/v1"]
    assert c.document_store.list_versions() == [f"{p.skill_id}/v1"]
    assert old_path.read_bytes() == old_bytes


def test_historical_bundle_with_stale_embedded_metadata_is_safely_normalized(tmp_path):
    c, d, child, _ = _complete(tmp_path)
    p = d.effective_skill_package
    # Reproduce the former independent saves rather than the corrected API.
    c.package_store.save(p, skill_id="old_copy", display_name="旧版副本")
    c.document_store.save(d, skill_id="old_copy", display_name="旧版副本")
    package, loaded, _ = _reload(_controller(tmp_path), "old_copy/v1")
    assert loaded.skill_template.event_patterns[0].pattern_id == child
    assert loaded.effective_skill_package == package
    c.configuration_service.require_current(loaded, package)


def test_legacy_document_without_business_projection_becomes_a_clean_baseline(tmp_path):
    from core.legacy_importer import import_skill_package

    c = _controller(tmp_path)
    p = _package()
    c.package_store.save(p)
    c.document_store.save(import_skill_package(p))
    package, loaded, _ = _reload(c, f"{p.skill_id}/v1")
    assert loaded.version == 1
    c.configuration_service.require_current(loaded, package)


def test_stable_loaded_group_remains_editable_and_can_be_saved_as_next_version(
    tmp_path,
):
    c, d, child, _ = _complete(tmp_path)
    p = d.effective_skill_package
    c.save_skill_bundle(c._dump(p), c._dump(d))
    _, loaded, _ = _reload(_controller(tmp_path), f"{p.skill_id}/v1")
    edited, _, _ = c.save_pattern_group(
        c._dump(loaded),
        "video",
        child,
        "重新编辑的子组",
        "sequence",
        ["branch:b", "branch:a"],
        7,
        1,
        "global",
    )
    published, effective, _ = c.unified_validate_apply(edited)
    c.save_skill_bundle(effective, published)
    reloaded_package, reloaded, _ = _reload(_controller(tmp_path), f"{p.skill_id}/v2")
    group = next(
        g for g in reloaded.skill_template.event_patterns if g.pattern_id == child
    )
    assert group.display_name == "重新编辑的子组"
    assert [s.source_ref for s in group.stages] == ["branch:b", "branch:a"]
    c.configuration_service.require_current(reloaded, reloaded_package)


@pytest.mark.parametrize("store_name", ["package_store", "document_store"])
def test_explicit_version_write_never_overwrites_existing_assets(tmp_path, store_name):
    c, d, _, _ = _complete(tmp_path)
    store = getattr(c, store_name)
    value = d.effective_skill_package if store_name == "package_store" else d
    path = store.save(value, version=1)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        store.save(value, version=1)
    assert path.read_bytes() == before


@pytest.mark.parametrize("selection", ["bad/vabc", "bad/v0", "bad/v-1"])
def test_invalid_saved_version_is_a_user_facing_error(tmp_path, selection):
    c = _controller(tmp_path)
    with pytest.raises(gr.Error, match="版本"):
        c.load_saved_skill(selection)


@pytest.mark.parametrize("field,value", [("skill_id", "other_skill"), ("version", 88)])
def test_runtime_metadata_must_match_selected_archive_version(tmp_path, field, value):
    c, d, _, _ = _complete(tmp_path)
    p = d.effective_skill_package
    c.save_skill_bundle(c._dump(p), c._dump(d))
    path = c.package_store.root / p.skill_id / "1.json"
    raw = json.loads(path.read_text("utf-8"))
    raw[field] = value
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(gr.Error, match="不匹配"):
        c.load_saved_skill(f"{p.skill_id}/v1")


def test_invalid_save_identity_is_rejected_without_creating_an_asset(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    with pytest.raises(gr.Error, match="保存完整技能失败"):
        c.save_skill_bundle(
            c._dump(d.effective_skill_package), c._dump(d), "../invalid"
        )
    assert not c.package_store.list_versions() and not c.document_store.list_versions()


def test_legacy_schema_document_migrates_without_losing_groups(tmp_path):
    c, d, child, parent = _complete(tmp_path)
    p = d.effective_skill_package
    c.save_skill_bundle(c._dump(p), c._dump(d))
    path = c.document_store.root / p.skill_id / "1.json"
    raw = json.loads(path.read_text("utf-8"))
    raw["schema_version"] = "3.1"
    raw["validation_report"].pop("configuration_publication", None)
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    package, loaded, _ = _reload(_controller(tmp_path), f"{p.skill_id}/v1")
    assert loaded.schema_version == "3.2"
    assert [g.pattern_id for g in loaded.skill_template.event_patterns] == [
        child,
        parent,
    ]
    c.configuration_service.require_current(loaded, package)
