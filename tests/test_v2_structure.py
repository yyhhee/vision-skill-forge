"""Behavioral characterization of the original five-page component/event graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def workspace_fingerprint(app, temporary_root: Path) -> dict[str, object]:
    """Normalize process-local IDs while retaining component settings and edges."""
    config = app.get_config_file()
    # The workbench is a read-only addition; compare every original editor
    # component and callback against the immutable fixture, not a new baseline.
    workbench_ids = {
        c["id"]
        for c in config["components"]
        if str(c["props"].get("elem_id", "")).startswith("skill-workbench-")
    }
    assert len(workbench_ids) == 6
    config["dependencies"] = [
        d
        for d in config["dependencies"]
        if getattr(app.fns[d["id"]].fn, "__name__", None)
        not in {"workbench_controls", "_workbench_navigate"}
    ]
    for component in config["components"]:
        if component["type"] == "tabitem" and component["props"].get("id") in {
            "conditions",
            "groups",
            "final",
            "outputs",
            "trigger",
        }:
            component["props"].pop("id")
    # Output forms intentionally replace free-text cells; their executable
    # contracts have focused tests. Project only these explicit changes onto
    # the original event graph instead of replacing its immutable baseline.
    output_ids = {
        c["id"]
        for c in config["components"]
        if str(c["props"].get("elem_id", "")).startswith("output-editor-")
    }
    output_table = next(
        c["id"]
        for c in config["components"]
        if c["props"].get("label") == "业务输出规格"
    )
    output_delete_choice = next(
        c["id"]
        for c in config["components"]
        if c["props"].get("label") == "选择要删除的输出"
    )
    for dep in config["dependencies"]:
        callback = getattr(app.fns[dep["id"]].fn, "__name__", None)
        if callback == "output_editor_new":
            assert len(dep["inputs"]) == 0 and len(dep["outputs"]) == 1
            dep["inputs"], dep["outputs"] = [output_table], [output_table]
            dep["output_callback"] = "business_add_output_row"
        elif callback == "delete_output_form":
            assert len(dep["inputs"]) == 2 and len(dep["outputs"]) == 3
            dep["inputs"], dep["outputs"] = (
                [output_table, output_delete_choice],
                [output_table],
            )
            dep["output_callback"] = "business_delete_output_row"
        elif callback == "save_output_form":
            assert len(dep["inputs"]) == 9 and len(dep["outputs"]) == 3
            dep["inputs"] = [dep["inputs"][0], output_table]
            dep["outputs"] = dep["outputs"][:2]
            dep["output_callback"] = "business_apply_outputs"
    config["dependencies"] = [
        d
        for d in config["dependencies"]
        if getattr(app.fns[d["id"]].fn, "__name__", None)
        not in {
            "output_editor_choices",
            "output_editor_controls",
            "output_editor_kinds",
        }
    ]
    for component in config["components"]:
        props = component["props"]
        if component["id"] == output_table:
            assert props["interactive"] is False
            props["interactive"] = True
        if component["id"] == output_delete_choice:
            assert props["visible"] is False
            props["visible"] = True
        if props.get("value") in ("删除所选输出", "保存业务输出到草稿"):
            assert props["interactive"] is False
            props["interactive"] = True
        if str(props.get("value", "")).startswith("下表用于查看已保存到草稿的输出；"):
            props["value"] = (
                "来源和“希望看到”必须类型兼容；展示方式属于 PresentationSpec，只改变布局时不会重新调用视觉模型。"
            )
    # Added group controls have their own tests; retain the original subgraph.
    pattern_ids = {
        c["id"]
        for c in config["components"]
        if str(c["props"].get("elem_id", "")).startswith("pattern-editor-")
    }
    for dep in config["dependencies"]:
        callback = getattr(app.fns[dep["id"]].fn, "__name__", None)
        if callback == "pattern_secondary_controls":
            dep["pattern_callback"] = "business_secondary_controls"
        elif callback == "save_pattern_group":
            assert len(dep["inputs"]) == 9 and len(dep["outputs"]) == 3
            dep["inputs"] = dep["inputs"][:2] + dep["inputs"][4:]
            dep["outputs"] = dep["outputs"][:2]
            dep["pattern_callback"] = "business_apply_pattern"
    config["dependencies"] = [
        d
        for d in config["dependencies"]
        if getattr(app.fns[d["id"]].fn, "__name__", None)
        not in {
            "pattern_group_choices",
            "pattern_group_controls",
            "pattern_form_preview",
        }
        and not any(target in pattern_ids for target, _ in d["targets"])
    ]
    for component in config["components"]:
        props = component["props"]
        if props.get("label") == "基础关系":
            assert props["filterable"] is False
            props["filterable"] = True
        if props.get("label") == "相邻步骤最长间隔（秒，0 为不限制）":
            props["label"] = "相邻步骤最长间隔（秒，可不限制）"
        if str(props.get("value", "")).startswith(
            "选中已有组即可修改；也可以选择“新建编排组”。"
        ):
            props["value"] = (
                "把分支组合成可复用的编排组。先保存“顺序（A → B）”，再把该已编排组与分支 C 选择“并行”，即可得到“（A → B）AND C”；顺序关系只适用于视频。"
            )
    # Time editing deliberately replaces one panel. Verify its additions in
    # test_time_configuration, then compare the untouched historical subgraph.
    time_ids = {
        c["id"]
        for c in config["components"]
        if str(c["props"].get("elem_id", "")).startswith("time-configuration-")
    }
    time_ids |= pattern_ids
    time_ids |= output_ids
    time_ids |= workbench_ids
    component_types = {c["id"]: c["type"] for c in config["components"]}

    def remove_time_forms(node):
        for child in node.get("children", []):
            remove_time_forms(child)
        children = node.get("children", [])
        if (
            children
            and component_types.get(node["id"]) == "form"
            and all(c["id"] in time_ids for c in children)
        ):
            time_ids.add(node["id"])

    remove_time_forms(config["layout"])
    activation_time_excluded = time_ids.copy()
    time_apply = next(
        c["id"]
        for c in config["components"]
        if c["props"].get("value") == "保存所选对象的时间设置到草稿"
    )
    by_dependency = {d["id"]: d for d in config["dependencies"]}
    for dep in config["dependencies"]:
        name = getattr(app.fns[dep["id"]].fn, "__name__", None)
        if name == "time_configuration_controls":
            previous = by_dependency.get(dep.get("trigger_after"))
            if (
                previous
                and getattr(app.fns[previous["id"]].fn, "__name__", None)
                == "time_configuration_targets"
            ):
                dep["targets"] = previous["targets"]
                dep["trigger_mode"] = previous["trigger_mode"]
            dep["inputs"] = dep["inputs"][:2]
            dep["outputs"] = dep["outputs"][:10]
            dep["time_callback"] = "business_branch_time_controls"
        elif name == "save_time_configuration":
            assert len(dep["inputs"]) == 13
            dep["inputs"] = dep["inputs"][:2] + dep["inputs"][3:-1]
            dep["time_callback"] = "business_apply_branch_time"
    config["dependencies"] = [
        d
        for d in config["dependencies"]
        if getattr(app.fns[d["id"]].fn, "__name__", None)
        not in {"time_configuration_targets", "time_configuration_visibility"}
        and not any(target in time_ids for target, _ in d["targets"])
    ]
    for component in config["components"]:
        props = component["props"]
        label = props.get("label")
        if component["id"] == time_apply:
            props["value"] = "保存分支时间到草稿"
        if label == "时间设置｜选择条件或整个分支":
            props["label"] = "分支时间与有效状态｜持续、累计、窗口占比"
        if label == "什么时候算满足":
            props["label"] = "时间约束"
            props["choices"] = [
                ("立即判断", "immediate"),
                ("连续满足", "continuous"),
                ("窗口内累计满足", "cumulative"),
                ("窗口内满足占比", "ratio"),
            ]
        if label in {
            "持续/累计时间（秒）",
            "观察窗口（秒）",
            "窗口满足比例（%）",
            "允许短暂中断（秒）",
            "按谁分别计时",
            "分支结果产生方式",
            "成立后保持（秒）",
        }:
            props["visible"] = True
        if label == "按谁分别计时":
            props["label"] = "按什么对象连续"
            props.pop("info", None)
            props["choices"][0] = ("当前媒体内全局", "global")
        if label == "分支结果产生方式":
            props["choices"] = [
                ("首次满足", "first"),
                ("允许重复形成事件", "repeat"),
                ("状态变化时", "on_change"),
            ]
        if props.get("value") == "请先选择要修改的条件或整个分支。":
            props["value"] = "当前分支立即判断，不附加持续约束。"
        if str(props.get("value", "")).startswith("先选择作用对象，再设置等待多久。"):
            props["value"] = (
                "时间约束独立作用于当前分支，不会误用到其它分支。图片只能立即判断；视频可按同一目标、轨迹、目标对或区域持续。"
            )
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
    activation_ids |= activation_time_excluded
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
            "callback": item["output_callback"]
            if item.get("output_callback")
            else item["pattern_callback"]
            if item.get("pattern_callback")
            else item["time_callback"]
            if item.get("time_callback")
            else "restore_default_editor_document"
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
