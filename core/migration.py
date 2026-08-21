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
    variants = {
        media_type: {
            "media_type": media_type,
            "status": "executable",
            "nodes": [node.model_dump(mode="json") for node in spec.nodes],
            "outputs": dict(spec.outputs),
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
