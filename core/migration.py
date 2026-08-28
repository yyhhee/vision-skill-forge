from __future__ import annotations

import hashlib
import json

from .schema import CanonicalSemanticIR, SkillPackage, VisualSkillSpec


def _infer_target(spec: VisualSkillSpec) -> tuple[str, str, list[str]]:
    for node in spec.nodes:
        if node.op != "rex.ground@1.0":
            continue
        targets = node.params.get("targets", [])
        if not targets:
            continue
        target = targets[0]
        phrases = [str(value) for value in target.get("phrases", []) if value]
        label = str(target.get("label") or spec.display_name)
        return label, label, phrases or [label]
    return spec.display_name, spec.original_instruction, [spec.original_instruction]


def _semantic_hash(data: dict) -> str:
    canonical = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _rewrite_reference(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_rewrite_reference(item, replacements) for item in value]
    return value


def _next_id(base: str, used_ids: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _upgrade_v1_nodes(spec: VisualSkillSpec) -> tuple[list[dict], dict[str, str]]:
    """Convert retired V1 atoms to their explicit current equivalents."""

    replacements: dict[str, str] = {}
    upgraded: list[dict] = []
    deduplicated_ids: set[str] = set()
    used_ids = {node.id for node in spec.nodes}
    for node in spec.nodes:
        item = node.model_dump(mode="json")
        params = dict(item["params"])
        if item["op"] == "video.sample@1.0":
            item["op"] = "video.sample@1.1"
            if params.get("mode") == "interval":
                params["interval_seconds"] = params.get("interval_seconds", 1.0)
        elif item["op"] == "image.resize@1.0":
            item["op"] = "image.resize@1.1"
        elif item["op"] == "image.tile@1.0":
            item["op"] = "image.tile@1.1"
            overlap = params.get("overlap", 0.2)
            params["overlap_x"] = params.get("overlap_x", overlap)
            params["overlap_y"] = params.get("overlap_y", overlap)
            params.pop("overlap", None)
            params.pop("deduplicate_iou", None)
            params.pop("deduplicate_mode", None)
        elif item["op"] == "rex.ground@1.0":
            item["op"] = "rex.ground@1.1"
            deduplicated_id = _next_id(f"{item['id']}_deduplicated", used_ids)
            deduplicated_ids.add(deduplicated_id)
            replacements[f"${item['id']}"] = f"${deduplicated_id}"
            upgraded.append(item)
            upgraded.append(
                {
                    "id": deduplicated_id,
                    "op": "objects.deduplicate@1.0",
                    "inputs": {"objects": f"${item['id']}"},
                    "params": {
                        "metric": params.pop("deduplicate_metric", "iou"),
                        "threshold": params.pop("deduplicate_iou", 0.7),
                        "keep": "first",
                    },
                    "enabled": item["enabled"],
                }
            )
            item["params"] = params
            continue
        elif item["op"] == "temporal.sequence@1.0":
            item["op"] = "temporal.sequence@2.0"
            maximum = params.pop("max_gap_seconds", 5.0)
            steps = params.pop("steps", [])
            item["params"] = {
                "transitions": [
                    {
                        "relation": "after",
                        "source_anchor": "end",
                        "target_anchor": "start",
                        "minimum_delay_seconds": 0.0,
                        "maximum_delay_seconds": maximum,
                    }
                    for _ in range(max(0, len(item["inputs"].get("events", [])) - 1))
                ],
                "correlation_scope": "track" if params.pop("same_key", True) else "global",
                "correlation_fields": [],
                "consume_events": True,
                "label": steps[-1] if steps else "顺序事件",
            }
            upgraded.append(item)
            continue
        item["params"] = params
        upgraded.append(item)

    for item in upgraded:
        if item["id"] in deduplicated_ids:
            continue
        item["inputs"] = {
            name: _rewrite_reference(value, replacements)
            for name, value in item["inputs"].items()
        }
    return upgraded, replacements


def migrate_v1_spec(spec: VisualSkillSpec) -> SkillPackage:
    """Explicitly wrap a V1 workflow; inferred semantics always require review."""
    concept, source_span, phrases = _infer_target(spec)
    semantic_data = {
        "schema_version": "1.0",
        "mode": "direct_grounding",
        "target": {
            "concept": concept,
            "source_span": source_span,
            "phrases": phrases,
        },
        "constraints": [],
        "logic": "all",
        "unresolved": [],
    }
    semantic_data["semantic_hash"] = _semantic_hash(semantic_data)
    semantic_ir = CanonicalSemanticIR.model_validate(semantic_data)
    nodes, replacements = _upgrade_v1_nodes(spec)
    variants = {
        media_type: {
            "media_type": media_type,
            "status": "executable",
            "nodes": nodes,
            "outputs": {
                name: _rewrite_reference(value, replacements)
                for name, value in spec.outputs.items()
            },
        }
        for media_type in spec.input.accept
    }
    return SkillPackage.model_validate(
        {
            "schema_version": "2.0",
            "skill_id": spec.name,
            "version": 1,
            "display_name": spec.display_name,
            "original_instruction": spec.original_instruction,
            "compile_status": "needs_review",
            "input": {
                "requested_accept": list(spec.input.accept),
                "accept": list(spec.input.accept),
            },
            "semantic_ir": semantic_ir.model_dump(mode="json"),
            "variants": variants,
            "compatibility_issues": [
                {
                    "media_type": spec.input.accept[0],
                    "code": "v1_semantics_inferred",
                    "message": "旧技能仅迁移工作流；规范语义由 targets 推断，需人工确认",
                }
            ],
        }
    )


__all__ = ["migrate_v1_spec"]
