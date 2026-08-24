from __future__ import annotations

from copy import deepcopy
from typing import Any

from .document_hashes import refresh_document_hashes
from .editor_schema import CURRENT_EDITOR_SCHEMA_VERSION, SkillEditorDocument


_RESULT_TYPE_MAP = {
    "boolean": ("boolean", "single", "status"),
    "object_list": ("entity_set", "list", "entities"),
    "count": ("scalar", "single", "count"),
    "measurement": ("scalar", "single", "value"),
    "direction": ("scalar", "single", "value"),
    "track": ("track_set", "list", "tracks"),
    "event": ("event_set", "list", "events"),
    "timeline": ("timeline", "series", "stages"),
    "notification": ("decision", "single", "status"),
    "annotated_media": ("media", "single", "media"),
}


def _result_defaults(spec: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(spec)
    legacy = result.get("result_type")
    semantic_type, value_shape, projection = _RESULT_TYPE_MAP.get(
        legacy, ("scalar", "single", "identity")
    )
    result.setdefault("semantic_type", semantic_type)
    result.setdefault("value_shape", value_shape)
    result.setdefault("projection", {"kind": projection, "parameters": {}})
    outputs = result.get("required_outputs") or []
    if result.get("source_ref") is None and outputs:
        result["source_ref"] = f"output:{outputs[0]}"
    result.setdefault("unit", None)
    result.setdefault("grouping", [])
    result.setdefault("condition_snapshot_policy", "on_result")
    result.setdefault(
        "label_policy",
        {
            "business_label": None,
            "preserve_model_label": True,
            "fallback_to_model_label": True,
        },
    )
    result.setdefault("save_policy", "always")
    result.setdefault("evidence_policy", "optional")
    result.setdefault("empty_policy", "empty")
    return result


def _default_final_decision(specs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not specs:
        return None
    priority = {
        "event_set": 0,
        "timeline": 1,
        "decision": 2,
        "scalar": 3,
        "entity_set": 4,
        "track_set": 5,
        "boolean": 6,
        "resource": 7,
        "media": 8,
    }
    primary = min(
        specs,
        key=lambda item: (
            priority.get(item.get("semantic_type", "scalar"), 99),
            item.get("result_id", ""),
        ),
    )
    semantic_type = primary.get("semantic_type")
    projection = (primary.get("projection") or {}).get("kind")
    if semantic_type == "event_set":
        decision_type = "event_decision"
    elif semantic_type == "timeline":
        decision_type = "timeline_summary"
    elif semantic_type == "scalar" and projection in {"count", "value", "duration"}:
        decision_type = "measurement_decision"
    elif semantic_type in {"entity_set", "track_set"}:
        decision_type = "detection_summary"
    else:
        decision_type = "state_summary"
    return {
        "decision_id": "primary",
        "display_name": primary.get("display_name") or "最终结果",
        "decision_type": decision_type,
        "source_ref": f"result:{primary['result_id']}",
        "success_condition": {},
        "show_reason": True,
        "show_failed_or_pending_branches": True,
        "overview_order": 0,
    }


def migrate_3_0_to_3_1(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != "3.0":
        raise ValueError("migrate_3_0_to_3_1 requires schema_version 3.0")
    result = deepcopy(data)
    template = result.setdefault("skill_template", {})
    specs = [_result_defaults(item) for item in template.get("result_specs", [])]
    template["result_specs"] = specs
    for branch in template.get("business_branches", []):
        if branch.get("condition_root") is None and branch.get("root_node_id"):
            branch["condition_root"] = {
                "expression_id": f"{branch['branch_id']}_root",
                "operator": "ATOM",
                "display_name": branch.get("display_name") or branch["branch_id"],
                "source_ref": f"node:{branch['root_node_id']}",
                "parameters": {},
                "children": [],
                "required_count": None,
                "enabled": branch.get("enabled", True),
            }
    if template.get("final_decision") is None:
        template["final_decision"] = _default_final_decision(specs)
    is_event = (
        template.get("final_decision", {}).get("decision_type") == "event_decision"
        if template.get("final_decision")
        else False
    )
    trigger_policy = template.get("trigger_policy") or {}
    if is_event and trigger_policy.get("mode", "none") == "none":
        trigger_policy["mode"] = "once"
    trigger_policy.setdefault("mode", "none")
    trigger_policy.setdefault("cooldown_seconds", 0.0)
    trigger_policy.setdefault("severity", "medium")
    trigger_policy.setdefault("outputs", ["event_record"])
    template["trigger_policy"] = trigger_policy
    template.setdefault("presentation_specs", [])
    result.setdefault(
        "readiness",
        {
            "draft_valid": True,
            "review_complete": not bool(template.get("pending_decisions")),
            "compile_valid": result.get("effective_skill_package") is not None,
            "runtime_ready": bool(
                (result.get("validation_report") or {}).get("can_run", False)
            ),
            "publish_ready": False,
            "reasons": [],
        },
    )
    result.setdefault(
        "hashes",
        {
            "semantic_hash": None,
            "compile_hash": None,
            "package_hash": None,
            "presentation_hash": None,
        },
    )
    result.setdefault("compiled_artifact_ref", None)
    result["schema_version"] = "3.1"
    return result


def migrate_3_1_to_3_2(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema_version") != "3.1":
        raise ValueError("migrate_3_1_to_3_2 requires schema_version 3.1")
    result = deepcopy(data)
    template = result.setdefault("skill_template", {})
    existing = {
        item.get("result_id"): item
        for item in template.get("presentation_specs", [])
        if item.get("result_id")
    }
    presentations = []
    for index, spec in enumerate(template.get("result_specs", [])):
        result_id = spec["result_id"]
        presentation = existing.get(result_id) or {
            "result_id": result_id,
            "preferred_renderer": "generic.summary",
            "show_in_overview": True,
            "display_order": index,
            "overview_span": "normal",
            "value_format": "auto",
            "precision": None,
            "sort_by": None,
            "visualization_options": {},
            "interaction_policy": {
                "drilldown": True,
                "highlight_evidence": True,
                "default_focus": "summary",
            },
        }
        presentations.append(presentation)
    template["presentation_specs"] = presentations
    result["schema_version"] = "3.2"
    return result


def migrate_editor_data(
    value: SkillEditorDocument | dict[str, Any],
) -> dict[str, Any]:
    data = (
        value.model_dump(mode="json")
        if isinstance(value, SkillEditorDocument)
        else deepcopy(value)
    )
    version = data.get("schema_version")
    if version == "3.0":
        data = migrate_3_0_to_3_1(data)
        version = data["schema_version"]
    if version == "3.1":
        data = migrate_3_1_to_3_2(data)
        version = data["schema_version"]
    if version != CURRENT_EDITOR_SCHEMA_VERSION:
        raise ValueError(f"unsupported SkillEditorDocument schema: {version}")
    return data


def migrate_editor_document(
    value: SkillEditorDocument | dict[str, Any],
) -> SkillEditorDocument:
    document = SkillEditorDocument.model_validate(migrate_editor_data(value))
    return refresh_document_hashes(document)


def migration_report(
    value: SkillEditorDocument | dict[str, Any],
) -> dict[str, Any]:
    before = (
        value.schema_version
        if isinstance(value, SkillEditorDocument)
        else value.get("schema_version")
    )
    migrated = migrate_editor_document(value)
    return {
        "from_version": before,
        "to_version": migrated.schema_version,
        "changed": before != migrated.schema_version,
        "semantic_hash": migrated.hashes.semantic_hash,
        "presentation_hash": migrated.hashes.presentation_hash,
    }


__all__ = [
    "migrate_3_0_to_3_1",
    "migrate_3_1_to_3_2",
    "migrate_editor_data",
    "migrate_editor_document",
    "migration_report",
]
