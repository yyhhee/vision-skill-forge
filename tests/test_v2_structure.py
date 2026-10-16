"""Behavioral characterization of the original five-page component/event graph."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def workspace_fingerprint(app, temporary_root: Path) -> dict[str, object]:
    """Normalize process-local IDs while retaining component settings and edges."""
    config = app.get_config_file()
    ids = {item["id"]: index for index, item in enumerate(config["components"])}

    def layout(node):
        return {
            "id": ids.get(node["id"], "root"),
            "children": [layout(child) for child in node.get("children", [])],
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
            "inputs": [ids[index] for index in item["inputs"]],
            "outputs": [ids[index] for index in item["outputs"]],
            "trigger_after": item.get("trigger_after"),
            "trigger_only_on_success": item.get("trigger_only_on_success"),
            "trigger_mode": item.get("trigger_mode"),
            "queue": item.get("queue"),
            "js": item.get("js"),
            "callback": getattr(app.fns[item["id"]].fn, "__name__", None),
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
