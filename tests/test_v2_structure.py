"""Behavioral characterization of the original five-page component/event graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def workspace_fingerprint(app, temporary_root: Path) -> dict[str, object]:
    """Normalize process-local IDs while retaining component settings and edges."""
    config = app.get_config_file()
    restore_id = next(
        item["id"]
        for item in config["components"]
        if item["type"] == "button"
        and item["props"].get("value") == "还原本次生成/加载的默认规则"
    )
    for dependency in config["dependencies"]:
        if [restore_id, "click"] in [list(target) for target in dependency["targets"]]:
            assert app.fns[dependency["id"]].fn.__name__ == "_restore_generated"
            assert len(dependency["inputs"]) == 4
            assert len(dependency["outputs"]) == 3
            dependency["inputs"] = [dependency["inputs"][0], dependency["inputs"][3]]
            dependency["outputs"] = dependency["outputs"][:2]
            # Compare the original subgraph except this deliberately replaced
            # callback, whose staged restore semantics have their own test.
            dependency["lifecycle_restore"] = True
    # The activation controls are an intentional addition after the pure
    # refactor. Keep checking the complete original subgraph against bf71b22.
    activation_ids = {
        item["id"]
        for item in config["components"]
        if str(item["props"].get("elem_id", "")).startswith("configuration-lifecycle-")
    }
    config["components"] = [
        item for item in config["components"] if item["id"] not in activation_ids
    ]
    # Intentional lifecycle copy changes: assert the new copy before comparing
    # all remaining properties against the immutable pre-feature fixture.
    draft_labels = {
        "保存当前参数到草稿": "应用这个参数",
        "保存逻辑到草稿": "保存这组逻辑",
        "保存分支时间到草稿": "应用分支时间设置",
        "保存编排组到草稿": "保存当前编排组",
        "保存最终判定到草稿": "应用最终判定",
        "保存业务输出到草稿": "应用业务输出",
        "保存触发策略到草稿": "应用触发策略",
    }
    activation_labels = iter(
        ["校验并生成当前运行版本（使修改生效）", "完整校验并应用为当前运行版本"]
    )
    draft_count = 0
    apply_count = 0
    for item in config["components"]:
        props = item["props"]
        value = props.get("value")
        if item["type"] == "button" and value in draft_labels:
            draft_count += 1
            props["value"] = draft_labels[value]
        elif item["type"] == "button" and value == "应用修改，更新运行版本":
            apply_count += 1
            props["value"] = next(activation_labels)
        elif item["type"] == "markdown" and isinstance(value, str):
            props["value"] = value.replace(
                "必须点击 **【应用修改，更新运行版本】**（本页顶部与下方是同一个操作）；",
                "必须点击下方 **【校验并生成当前运行版本（使修改生效）】**；",
            )
    assert draft_count == 8
    assert apply_count == 2
    config["dependencies"] = [
        item
        for item in config["dependencies"]
        if not activation_ids.intersection(item["inputs"] + item["outputs"])
        and not any(target in activation_ids for target, _ in item["targets"])
        and getattr(app.fns[item["id"]].fn, "__name__", None)
        != "load_editor_configuration"
    ]
    all_dependencies = app.get_config_file()["dependencies"]
    by_id = {item["id"]: item for item in all_dependencies}
    kept = {item["id"]: index for index, item in enumerate(config["dependencies"])}

    def original_predecessor(dependency):
        predecessor = dependency.get("trigger_after")
        while predecessor is not None and predecessor not in kept:
            predecessor = by_id[predecessor].get("trigger_after")
        return kept.get(predecessor)

    ids = {item["id"]: index for index, item in enumerate(config["components"])}

    def layout(node):
        return {
            "id": ids.get(node["id"], "root"),
            "children": [
                layout(child)
                for child in node.get("children", [])
                if child["id"] not in activation_ids
            ],
        }

    components = [
        {
            "type": item["type"],
            "props": {
                key: value
                for key, value in item["props"].items()
                if key not in {"proxy_url", "name"}
            },
        }
        for item in config["components"]
    ]
    dependencies = [
        {
            "targets": [
                (ids.get(target, "root"), event) for target, event in item["targets"]
            ],
            "inputs": [
                ids[index]
                for index in (
                    item["inputs"][1:]
                    if getattr(app.fns[item["id"]].fn, "configuration_guard", False)
                    else item["inputs"]
                )
            ],
            "outputs": [ids[index] for index in item["outputs"]],
            "trigger_after": original_predecessor(item),
            "trigger_only_on_success": item.get("trigger_only_on_success"),
            "trigger_mode": item.get("trigger_mode"),
            "queue": item.get("queue"),
            "js": item.get("js"),
            "callback": "restore_default_editor_document"
            if item.get("lifecycle_restore")
            else getattr(app.fns[item["id"]].fn, "__name__", None),
        }
        for item in config["dependencies"]
    ]

    def digest(value):
        text = json.dumps(value, sort_keys=True, ensure_ascii=False)
        # This root is different for each fixture invocation.
        text = text.replace(
            str(temporary_root).replace("\\", "\\\\"), "<temporary_root>"
        )
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    return {
        "component_count": len(components),
        "dependency_count": len(dependencies),
        "components": digest(components),
        "layout": digest(layout(config["layout"])),
        "dependencies": digest(dependencies),
        "stylesheet": digest(config.get("css")),
        "annotation_javascript": digest(config.get("js")),
    }


def test_original_workspace_component_and_event_graph_is_preserved(
    tmp_path: Path,
) -> None:
    from app_v2 import V2AppController, build_v2_app
    from core.registry import build_default_registry

    controller = V2AppController(
        registry=build_default_registry(),
        package_root=tmp_path / "skills",
        run_root=tmp_path / "runs",
        planner=None,
        rex=None,
    )
    app = build_v2_app(controller)
    try:
        expected = json.loads(
            (Path(__file__).parent / "fixtures/v2_workspace_bf71b22.json").read_text(
                "utf-8"
            )
        )
        assert workspace_fingerprint(app, tmp_path) == expected
        # Each delete callback must retain its own card index after extraction.
        delete_callbacks = [
            dependency.fn
            for dependency in app.fns.values()
            if dependency.fn is not None
            and "_remove_event_card" in dependency.fn.__code__.co_freevars
        ]
        assert len(delete_callbacks) == 6
        for index, callback in enumerate(delete_callbacks):
            response = callback(json.dumps([True] * 6))
            expected_active = [position != index for position in range(6)]
            assert json.loads(response[0]) == expected_active
            assert [item["visible"] for item in response[1:]] == expected_active
    finally:
        app.close()
