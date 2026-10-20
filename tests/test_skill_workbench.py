"""Skill-wide navigation reads the real draft without changing its semantics."""

import asyncio
import json
from pathlib import Path

import gradio as gr
import pytest
from gradio.state_holder import SessionState
from test_complete_skill_assets import _complete
from test_generic_editor_ui import _controller, _package

from app_v2 import build_v2_app
from core.editor_schema import ResultSpec
from ui.v2.controllers.workbench import (
    NAVIGATION_FIELDS,
    WorkbenchItem,
    render_workbench,
)


def test_overview_includes_nested_groups_time_final_and_outputs(tmp_path):
    c, d, child, parent = _complete(tmp_path)
    raw = c._dump(d)
    items = c.workbench_items(raw, "video variant")
    branches = [i for i in items if i.kind == "branch"]
    assert len(branches) == 3
    assert "2.0 秒" in branches[0].detail
    groups = {i.identity: i for i in items if i.kind == "group"}
    assert set(groups) == {child, parent}
    assert "先A后B" in groups[parent].detail
    assert "10.0 秒" in groups[child].detail
    assert any(i.kind == "final" and "父组" in i.detail for i in items)
    assert any(i.kind == "output" for i in items)
    assert "冷却 4 秒" in next(i.detail for i in items if i.kind == "trigger")
    overview, choices, enabled = c.workbench_controls(raw, "video", None)
    assert "不是执行结果" in overview
    assert len(choices["choices"]) == len(items)
    assert enabled["interactive"]
    assert c._dump(d) == raw


@pytest.mark.parametrize(
    "kind,tab",
    [
        ("branch", "conditions"),
        ("condition", "conditions"),
        ("group", "groups"),
        ("final", "final"),
        ("output", "outputs"),
        ("trigger", "trigger"),
    ],
)
def test_navigation_loads_exact_selection_without_document_update(tmp_path, kind, tab):
    c, d, _, _ = _complete(tmp_path)
    raw = c._dump(d)
    item = next(i for i in c.workbench_items(raw, "video") if i.kind == kind)
    updates = c.workbench_navigation(raw, "video", item.address, True)
    assert updates["business_editor_tabs"]["selected"] == tab
    assert set(updates) <= set(NAVIGATION_FIELDS)
    assert "editor_document" not in updates
    if kind == "branch":
        assert updates["business_branch"].value == item.identity
        assert updates["business_time_target"]["value"] == "branch:a"
    elif kind == "condition":
        assert updates["business_condition"].value == item.identity
        assert updates["business_branch"].value == item.branch_id
    elif kind == "group":
        assert updates["pattern_editor_selector"]["value"] == item.identity
    elif kind == "output":
        assert updates["output_editor_selector"]["value"] == item.identity
    assert c._dump(d) == raw


def test_duplicate_names_have_distinct_stable_addresses(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    for b in d.skill_template.business_branches:
        b.display_name = "同名分支"
    items = [i for i in c.workbench_items(c._dump(d), "video") if i.kind == "branch"]
    assert len({i.label for i in items}) == len(items)
    assert len({i.address for i in items}) == len(items)
    for item in items:
        assert (
            c.workbench_target(c._dump(d), "video", item.address).identity
            == item.identity
        )


def test_cross_media_and_stale_navigation_are_rejected(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    raw = c._dump(d)
    item = next(i for i in c.workbench_items(raw, "video") if i.kind == "branch")
    for media, address in [
        ("image", item.address),
        ("video", "forged-id"),
        ("video", None),
    ]:
        with pytest.raises(gr.Error, match="重新选择"):
            c.workbench_target(raw, media, address)
    d.skill_template.business_branches = d.skill_template.business_branches[1:]
    with pytest.raises(gr.Error, match="重新选择"):
        c.workbench_target(c._dump(d), "video", item.address)


def test_refresh_preserves_selection_or_clears_it_without_auto_navigation(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    raw = c._dump(d)
    address = c.workbench_items(raw, "video")[0].address
    assert c.workbench_controls(raw, "video", address)[1]["value"] == address
    assert c.workbench_controls(raw, "image", address)[1]["value"] is None
    empty = c.workbench_controls("", "image", address)
    assert empty[1]["choices"] == [] and empty[2]["interactive"] is False
    invalid = c.workbench_controls("{invalid", "image", address)
    assert "暂不能读取" in invalid[0]


def test_output_media_and_disabled_branch_are_not_misrepresented(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    d.skill_template.business_branches[0].enabled = False
    d.skill_template.result_specs.append(
        ResultSpec(
            result_id="image_only",
            display_name="仅图片输出",
            semantic_type="entity_set",
            value_shape="list",
            source_ref="branch:a",
            media_types=["image"],
        )
    )
    items = c.workbench_items(c._dump(d), "video")
    assert "已停用" in next(i.detail for i in items if i.kind == "branch")
    assert not any(i.identity == "image_only" for i in items)


def test_render_escapes_names_and_never_leaks_addresses():
    item = WorkbenchItem(
        "branch",
        "secret-node-id",
        '<script>alert("x")</script>',
        '<img src=x onerror="alert(1)">',
    )
    html = render_workbench([item], "图片")
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html and "&lt;img" in html
    assert "secret-node-id" not in html


def test_legacy_package_uses_same_projection_without_model_calls(tmp_path):
    c = _controller(tmp_path)
    doc = c.load_editor_configuration(c._dump(_package()), "已保存技能")
    for media in ("image", "video"):
        items = c.workbench_items(doc, media)
        assert any(i.kind == "branch" for i in items)
        assert any(i.kind == "output" for i in items)
        assert c.workbench_controls(doc, media, None)[2]["interactive"]
    assert c.planner is None and c.rex is None


@pytest.mark.parametrize(
    "path",
    sorted((Path(__file__).resolve().parents[1] / "presets_v2").glob("P*.json")),
    ids=lambda path: path.stem,
)
def test_every_preset_projects_and_navigates_without_changing_package(tmp_path, path):
    """Structural compatibility only; not a new real-model accuracy acceptance."""
    c = _controller(tmp_path)
    package = path.read_text(encoding="utf-8")
    raw = c.load_editor_configuration(package, "预置演示技能")
    before = c._parse_editor_json(raw).model_dump(mode="json")
    for media in json.loads(package)["variants"]:
        items = c.workbench_items(raw, media)
        assert items and any(i.kind == "branch" for i in items)
        for item in items:
            if item.kind in {"branch", "group", "final", "output", "trigger"}:
                updates = c.workbench_navigation(raw, media, item.address, True)
                assert "editor_document" not in updates
    assert c._parse_editor_json(raw).model_dump(mode="json") == before
    assert path.read_text(encoding="utf-8") == package


def test_navigation_callback_is_wired_and_does_not_write_the_document(tmp_path):
    c, d, _, _ = _complete(tmp_path)
    app = build_v2_app(c)
    try:
        config = app.get_config_file()
        navigation = next(
            dep
            for dep in config["dependencies"]
            if getattr(app.fns[dep["id"]].fn, "__name__", None) == "_workbench_navigate"
        )
        ids = {i["id"]: i for i in config["components"]}
        assert all(
            ids[i]["props"].get("label") != "完整编辑文档（V3）"
            for i in navigation["outputs"]
        )
        item = next(
            i for i in c.workbench_items(c._dump(d), "video") if i.kind == "group"
        )
        values = app.fns[navigation["id"]].fn(c._dump(d), "video", item.address, True)
        assert all(key._id in navigation["outputs"] for key in values)
        assert len(NAVIGATION_FIELDS) == len(set(NAVIGATION_FIELDS))
        assert json.loads(item.address)[0] == "group"
    finally:
        app.close()


def test_navigation_runs_through_real_gradio_session_and_postprocessing(tmp_path):
    """Components constructed inside an event lack normal instance attributes."""
    c, d, _, _ = _complete(tmp_path)
    app = build_v2_app(c)
    raw = c._dump(d)

    async def scenario():
        state = SessionState(app)
        config = app.get_config_file()
        refresh = next(
            x for x in config["dependencies"] if x["api_name"] == "workbench_controls"
        )
        navigate = next(
            x for x in config["dependencies"] if x["api_name"] == "_workbench_navigate"
        )
        await app.process_api(refresh["id"], [raw, "video variant", None], state=state)
        for kind in ("branch", "condition", "group", "final", "output", "trigger"):
            item = next(i for i in c.workbench_items(raw, "video") if i.kind == kind)
            result = await app.process_api(
                navigate["id"], [raw, "video variant", item.address, True], state=state
            )
            assert result["data"][0]["selected"] in {
                "conditions",
                "groups",
                "final",
                "outputs",
                "trigger",
            }
            assert result["data"][1].startswith("已定位：")
        assert c._dump(d) == raw

    try:
        asyncio.run(scenario())
    finally:
        app.close()
