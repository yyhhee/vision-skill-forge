from __future__ import annotations

import hashlib
import json
from typing import Any

from .editor_schema import DocumentHashes, SkillEditorDocument
from .result_presentation_schema import presentation_hash


def _digest(value: Any) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def semantic_payload(document: SkillEditorDocument) -> dict[str, Any]:
    template = document.skill_template.model_dump(mode="json")
    template.pop("rule_graph", None)
    template.pop("rule_graphs", None)
    template.pop("presentation_specs", None)
    business_branches = []
    for branch in template.get("business_branches", []):
        semantic_branch = dict(branch)
        semantic_branch.pop("node_ids", None)
        semantic_branch.pop("root_node_id", None)
        business_branches.append(semantic_branch)
    result_specs = []
    for spec in template.get("result_specs", []):
        semantic_spec = dict(spec)
        semantic_spec.pop("required_outputs", None)
        semantic_spec.pop("result_type", None)
        result_specs.append(semantic_spec)
    return {
        "schema_family": "SkillEditorDocument@3.x",
        "skill": {
            "skill_id": template.get("skill_id"),
            "display_name": template.get("display_name"),
            "original_instruction": template.get("original_instruction"),
            "source_type": template.get("source_type"),
            "semantic_ir": template.get("semantic_ir"),
            "result_specs": result_specs,
            "business_branches": business_branches,
            "event_patterns": template.get("event_patterns"),
            "final_decision": template.get("final_decision"),
            "resource_requirements": template.get("resource_requirements"),
            "pending_decisions": template.get("pending_decisions"),
            "recipe_refs": template.get("recipe_refs"),
            "trigger_policy": template.get("trigger_policy"),
        },
        "user_overrides": [
            item.model_dump(mode="json") for item in document.user_overrides
        ],
    }


def compute_document_hashes(document: SkillEditorDocument) -> DocumentHashes:
    semantic = _digest(semantic_payload(document))
    compile_value = _digest(
        {
            "semantic_hash": semantic,
            "rule_graphs": {
                key: value.model_dump(mode="json")
                for key, value in sorted(document.skill_template.rule_graphs.items())
            },
            "user_overrides": [
                item.model_dump(mode="json") for item in document.user_overrides
            ],
        }
    )
    package = (
        _digest(document.effective_skill_package)
        if document.effective_skill_package is not None
        else None
    )
    presentation = presentation_hash(document.skill_template.presentation_specs)
    return DocumentHashes(
        semantic_hash=semantic,
        compile_hash=compile_value,
        package_hash=package,
        presentation_hash=presentation,
    )


def refresh_document_hashes(document: SkillEditorDocument) -> SkillEditorDocument:
    return document.model_copy(update={"hashes": compute_document_hashes(document)})


__all__ = [
    "compute_document_hashes",
    "refresh_document_hashes",
    "semantic_payload",
]
