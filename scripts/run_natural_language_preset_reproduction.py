from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from clients.v2_planner import DeepSeekSemanticPlanner
from core.business_capabilities import build_business_capability_registry
from core.business_rule_draft import apply_business_rule_draft
from core.business_rule_editor import BusinessRuleEditor
from core.editor_generation import build_editor_document
from core.editor_schema import SkillEditorDocument
from core.editor_service import EditorService
from core.registry import build_default_registry
from core.schema import SkillPackage


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "v3" / "preset_reproduction_manifest.json"
DEFAULT_OUTPUT = ROOT / "tests" / "natural_language_preset_reproduction.json"


class _ReplayCompletions:
    def __init__(self, contents: list[str]):
        self.contents = list(contents)

    def create(self, **_: Any):
        if not self.contents:
            raise RuntimeError("recorded planner outputs exhausted")
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=self.contents.pop(0))
            )]
        )


class _ReplayClient:
    def __init__(self, contents: list[str]):
        self.chat = SimpleNamespace(completions=_ReplayCompletions(contents))


def _load_replay_outputs(paths: list[Path]) -> dict[str, list[str]]:
    outputs: dict[str, list[str]] = {}
    for path in paths:
        payload = json.loads(path.read_text("utf-8"))
        for case in payload.get("cases", []):
            raw = case.get("planner_raw_outputs")
            if raw and case.get("preset_id") not in outputs:
                outputs[case["preset_id"]] = list(raw)
    return outputs


def _walk_conditions(items: list[dict[str, Any]]):
    for item in items:
        yield item
        yield from _walk_conditions(item.get("children", []))


def _draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    conditions = [
        condition
        for branch in draft["branches"]
        for condition in _walk_conditions(branch["conditions"])
        if condition.get("operator", "ATOM") == "ATOM"
    ]
    return {
        "media_requirement": draft["media_requirement"],
        "branch_count": len(draft["branches"]),
        "branch_media": [item["media_type"] for item in draft["branches"]],
        "branch_logic": [item.get("logic", "AND") for item in draft["branches"]],
        "capabilities": sorted(
            {
                item["capability_id"]
                for item in conditions
                if item.get("capability_id")
            }
        ),
        "temporal_modes": [
            item.get("time", {}).get("mode", "immediate")
            for item in draft["branches"]
        ],
        "resources": [
            {
                "resource_type": item["resource_type"],
                "semantic_role": item["semantic_role"],
                "minimum_items": item.get("minimum_items", 1),
            }
            for item in draft.get("resources", [])
        ],
        "result_kinds": [item["result_kind"] for item in draft["results"]],
        "pending_kinds": [
            item["kind"] for item in draft.get("pending_decisions", [])
        ],
    }


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        if "state" in value and "value" in value:
            return _json_value(value.get("value"))
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items())
            if key not in {"source", "recommended_value", "required_before"}
        }
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def _normalized_reference(value: Any) -> Any:
    if isinstance(value, str) and ":" in value:
        prefix = value.split(":", 1)[0]
        if prefix in {
            "condition", "branch", "final", "event", "measurement",
            "resource", "result", "node", "output",
        }:
            return f"{prefix}:*"
    if isinstance(value, list):
        return [_normalized_reference(item) for item in value]
    return value


def _condition_signature(item) -> dict[str, Any]:
    parameters = {
        key: _normalized_reference(_json_value(value))
        for key, value in sorted(item.parameters.items())
    }
    signature: dict[str, Any] = {
        "operator": item.operator,
        "capability_id": item.capability_id,
        "parameters": parameters,
        "enabled": item.enabled,
    }
    if item.required_count is not None:
        signature["required_count"] = item.required_count
    if item.children:
        signature["children"] = [_condition_signature(child) for child in item.children]
    return signature


def _workflow_signature(document: SkillEditorDocument) -> dict[str, Any]:
    package = document.effective_skill_package
    if package is None:
        return {}
    result: dict[str, Any] = {}
    for media_type, variant in sorted(package.variants.items()):
        node_indexes = {node.id: index for index, node in enumerate(variant.nodes)}

        def ref(value: Any) -> Any:
            if isinstance(value, str) and value.startswith("$"):
                node_id = value[1:]
                return "$input" if node_id == "input" else f"$node:{node_indexes.get(node_id, '?')}"
            if isinstance(value, list):
                return [ref(item) for item in value]
            return value

        nodes = []
        for node in variant.nodes:
            params = _json_value(node.params)
            # Coordinates and vectors belong to 02 scene configuration and
            # cannot be inferred from a sentence.  Preserve their presence and
            # shape while excluding scene-specific values from structure checks.
            if node.op.startswith("region.manual@") and "points" in params:
                points = params["points"]
                params["points"] = {
                    "configured": bool(points),
                    "point_count": len(points) if isinstance(points, list) else 0,
                }
            if node.op.startswith("direction.manual@"):
                for key in ("start", "end", "vector"):
                    if key in params:
                        params[key] = {"configured": bool(params[key])}
            nodes.append({
                "op": node.op,
                "inputs": {key: ref(value) for key, value in sorted(node.inputs.items())},
                "params": params,
                "enabled": node.enabled,
            })
        result[media_type] = {
            "status": variant.status,
            "nodes": nodes,
            "outputs": {key: ref(value) for key, value in sorted(variant.outputs.items())},
            "configuration_slots": sorted(
                [
                    {
                        "kind": slot.kind,
                        "required": slot.required,
                        "allowed_shapes": sorted(slot.allowed_shapes),
                        "minimum_items": slot.minimum_items,
                        "paired": bool(slot.key_source_slot_id),
                    }
                    for slot in variant.configuration_slots
                ],
                key=lambda item: json.dumps(item, sort_keys=True),
            ),
        }
    return result


def _semantic_signature(document: SkillEditorDocument) -> dict[str, Any]:
    semantic = document.skill_template.semantic_ir
    constraints = sorted(
        [
            {
                "kind": item.kind,
                "value": _json_value(item.value),
                "polarity": item.polarity,
                "temporal": item.temporal,
            }
            for item in semantic.constraints
        ],
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
    )
    return {
        "mode": semantic.mode,
        "target": {
            "concept": semantic.target.concept,
            "classes": sorted(
                [
                    {
                        "label": item.label,
                        "phrases": sorted(item.phrases),
                    }
                    for item in semantic.target.classes
                ],
                key=lambda item: item["label"],
            ),
        },
        "constraints": constraints,
        "logic": semantic.logic,
    }


def _editor_signature(document: SkillEditorDocument) -> dict[str, Any]:
    template = document.skill_template
    effective = document.effective_skill_package
    media = sorted(effective.variants) if effective is not None else sorted({
        branch.media_type for branch in template.business_branches
    })
    return {
        "media": media,
        "semantic_configuration": _semantic_signature(document),
        "conditions": [
            {
                "media_type": branch.media_type,
                "condition": (
                    _condition_signature(branch.condition_root)
                    if branch.condition_root is not None else None
                ),
            }
            for branch in template.business_branches
        ],
        "temporal": [
            {
                "media_type": branch.media_type,
                "qualifiers": [
                    {
                        "mode": item.mode,
                        "duration_seconds": _json_value(item.duration_seconds),
                        "observation_window_seconds": _json_value(
                            item.observation_window_seconds
                        ),
                        "allowed_gap_seconds": item.allowed_gap_seconds,
                        "required_ratio": item.required_ratio,
                        "minimum_occurrences": item.minimum_occurrences,
                        "identity_scope": item.identity_scope,
                        "emission": item.emission,
                    }
                    for item in branch.temporal_qualifiers
                ],
            }
            for branch in template.business_branches
        ],
        "resources": sorted(
            [
                {
                    "resource_type": item.resource_type,
                    "semantic_role": item.semantic_role,
                    "cardinality": _json_value(item.cardinality),
                    "binding_policy": item.binding_policy,
                    "allowed_shapes": sorted(item.allowed_shapes),
                    "pairing_policy": item.pairing_policy,
                    "required_before": item.required_before,
                    "media_types": sorted(item.media_types),
                }
                for item in template.resource_requirements
            ],
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        ),
        "results": sorted(
            [
                {
                    "semantic_type": item.semantic_type,
                    "value_shape": item.value_shape,
                    "source_ref": _normalized_reference(item.source_ref),
                    "media_types": sorted(item.media_types),
                    "projection": _json_value(item.projection),
                    "unit": item.unit,
                    "grouping": sorted(item.grouping),
                    "save_policy": item.save_policy,
                    "evidence_policy": item.evidence_policy,
                    "empty_policy": item.empty_policy,
                }
                for item in template.result_specs
            ],
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        ),
        "final_decision": (
            {
                "decision_type": template.final_decision.decision_type,
                "combination": template.final_decision.combination,
                "required_count": template.final_decision.required_count,
                "source_count": len(template.final_decision.source_refs),
                "media_source_counts": {
                    key: len(value)
                    for key, value in sorted(
                        template.final_decision.media_source_refs.items()
                    )
                },
            }
            if template.final_decision is not None else None
        ),
        "trigger_policy": _json_value(template.trigger_policy),
        "execution_structure": _workflow_signature(document),
    }


def _capabilities(
    document: SkillEditorDocument,
    editor: BusinessRuleEditor,
) -> list[str]:
    values: list[str] = []
    for branch in document.skill_template.business_branches:
        values.extend(
            row["capability_id"]
            for row in editor.condition_rows(document, branch.branch_id)
            if row.get("capability_id")
        )
    if document.effective_skill_package is not None:
        for variant in document.effective_skill_package.variants.values():
            values.extend(
                capability_id
                for node in variant.nodes
                if (
                    capability_id := editor._matched_capability_for_operator(
                        node.op
                    )
                )
            )
    return sorted(values)


def _compare_to_preset(
    actual: SkillEditorDocument,
    expected: SkillEditorDocument,
    required_capabilities: list[str],
    editor: BusinessRuleEditor,
) -> dict[str, Any]:
    actual_signature = _editor_signature(actual)
    expected_signature = _editor_signature(expected)
    facets = {
        key: actual_signature[key] == expected_signature[key]
        for key in expected_signature
    }
    actual_capabilities = _capabilities(actual, editor)
    expected_capabilities = _capabilities(expected, editor)
    required = sorted(set(required_capabilities))
    payload = json.dumps(actual_signature, ensure_ascii=False, sort_keys=True)
    expected_payload = json.dumps(expected_signature, ensure_ascii=False, sort_keys=True)
    return {
        "normalized_exact": all(facets.values()),
        "facet_equal": facets,
        "matching_facets": sum(facets.values()),
        "facet_count": len(facets),
        "required_capability_coverage": all(
            item in actual_capabilities for item in required
        ),
        "required_capabilities": required,
        "actual_capabilities": actual_capabilities,
        "preset_capabilities": expected_capabilities,
        "actual_signature_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        "preset_signature_hash": hashlib.sha256(
            expected_payload.encode("utf-8")
        ).hexdigest(),
        "semantic_actual": actual_signature["semantic_configuration"],
        "semantic_preset": expected_signature["semantic_configuration"],
    }


def run(
    output: Path = DEFAULT_OUTPUT,
    selected: set[str] | None = None,
    style: str = "free",
    replay_paths: list[Path] | None = None,
) -> dict[str, Any]:
    manifest = json.loads(MANIFEST.read_text("utf-8"))
    cases = [
        item
        for item in manifest["cases"]
        if not selected or item["preset_id"] in selected
    ]
    unknown = (selected or set()) - {item["preset_id"] for item in manifest["cases"]}
    if unknown:
        raise ValueError(f"unknown preset ids: {sorted(unknown)}")

    registry = build_default_registry()
    capabilities = build_business_capability_registry(registry)
    replay_outputs = _load_replay_outputs(replay_paths or [])
    business_editor = BusinessRuleEditor(capabilities, registry)
    editor_service = EditorService(registry)
    records: list[dict[str, Any]] = []

    for index, case in enumerate(cases, start=1):
        preset_id = case["preset_id"]
        package = SkillPackage.model_validate_json(
            (ROOT / "presets_v2" / case["package"]).read_text("utf-8")
        )
        instruction = (
            case["structured_text"]
            if style == "structured"
            else package.original_instruction
            if style == "preset"
            else case["free_text"]
        )
        expected_document = editor_service.apply(
            business_editor.prepare(
                build_editor_document(package, source_type="preset")
            )
        )
        print(f"[{index}/{len(cases)}] {preset_id} compile", flush=True)
        record: dict[str, Any] = {
            "preset_id": preset_id,
            "instruction_style": style,
            "instruction": instruction,
            "requested_media": case["media"],
            "execution_source": (
                "recorded_real_llm_output" if replay_paths else "live_llm"
            ),
        }
        try:
            planner = DeepSeekSemanticPlanner(
                registry,
                client=(
                    _ReplayClient(replay_outputs[preset_id])
                    if replay_paths and preset_id in replay_outputs
                    else None
                ),
            )
            if replay_paths and preset_id not in replay_outputs:
                raise ValueError("no recorded planner output for replay")
            compiled = planner.compile(
                instruction,
                requested_accept=case["media"],
                skill_id=f"nl_reproduction_{preset_id.lower()}",
                display_name=f"{preset_id} 自然语言复现",
            )
            record["planner_attempts"] = compiled.attempts
            record["planner_errors"] = compiled.errors
            record["planner_raw_outputs"] = compiled.raw_outputs
            if compiled.package is None:
                raise ValueError("planner returned needs_review")
            if compiled.business_draft is None:
                document = build_editor_document(
                    compiled.package, source_type="natural_language"
                )
                draft_summary = None
                generation_mode = "canonical_semantic_fallback"
            else:
                document = apply_business_rule_draft(
                    build_editor_document(
                        compiled.package, source_type="natural_language"
                    ),
                    compiled.business_draft,
                    capabilities,
                    requested_accept=case["media"],
                )
                draft_summary = _draft_summary(compiled.business_draft)
                generation_mode = "business_draft"
            document = editor_service.apply(document)
            effective = document.effective_skill_package
            if effective is None:
                raise ValueError("business draft did not produce an effective package")
            actual_media = sorted(effective.variants)
            expected_media = sorted(case["media"])
            record.update(
                {
                    "status": "compiled"
                    if actual_media == expected_media
                    else "semantic_mismatch",
                    "actual_media": actual_media,
                    "generation_mode": generation_mode,
                    "draft": draft_summary,
                    "can_run": bool(document.validation_report.get("can_run")),
                    "validation_errors": document.validation_report.get("errors", []),
                    "pending_decisions": [
                        item.model_dump(mode="json")
                        for item in document.skill_template.pending_decisions
                    ],
                    "resource_requirements": [
                        item.model_dump(mode="json")
                        for item in document.skill_template.resource_requirements
                    ],
                    "result_specs": [
                        item.model_dump(mode="json")
                        for item in document.skill_template.result_specs
                    ],
                    "variant_outputs": {
                        key: value.outputs
                        for key, value in effective.variants.items()
                    },
                    "preset_comparison": _compare_to_preset(
                        document,
                        expected_document,
                        case["editor_capabilities"],
                        business_editor,
                    ),
                }
            )
        except Exception as exc:
            record.update(
                {
                    "status": "failed",
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                }
            )
        records.append(record)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps({"cases": records}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[{index}/{len(cases)}] {preset_id} {record['status']}", flush=True)

    data = {
        "schema_version": "1.0",
        "date": str(date.today()),
        "scope": "real_planner_compile_and_business_editor_reproduction",
        "instruction_style": style,
        "execution_source": (
            "recorded_real_llm_output" if replay_paths else "live_llm"
        ),
        "case_count": len(records),
        "compiled": sum(item["status"] == "compiled" for item in records),
        "semantic_mismatch": sum(
            item["status"] == "semantic_mismatch" for item in records
        ),
        "failed": sum(item["status"] == "failed" for item in records),
        "cases": records,
    }
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                key: data[key]
                for key in ("case_count", "compiled", "semantic_mismatch", "failed")
            }
        ),
        flush=True,
    )
    return data


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--preset", action="append", default=[])
    parser.add_argument(
        "--style", choices=["free", "structured", "preset"], default="free"
    )
    parser.add_argument("--replay-from", action="append", type=Path, default=[])
    args = parser.parse_args()
    run(
        args.output,
        set(args.preset) or None,
        args.style,
        args.replay_from or None,
    )


if __name__ == "__main__":
    main()
