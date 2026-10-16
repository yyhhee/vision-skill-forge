"""Controlled output editing backed by deterministic lowering and runtime types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .business_result_projector import build_runtime_contract, projection_accepts_type
from .business_rule_compiler import BusinessRuleCompiler, CompiledValue
from .business_rule_editor import (
    RESULT_KIND_SCHEMA,
    BusinessRuleEditError,
    BusinessRuleEditor,
)
from .document_hashes import refresh_document_hashes
from .editor_schema import ResultProjection, ResultSpec, SkillEditorDocument
from .result_presentation_schema import PresentationSpec
from .rule_graph import RuleGraphCompiler
from .runtime_values import contract_type_and_shape

_OUTPUT_LABELS = {
    "objects": "检测目标",
    "tracks": "目标轨迹",
    "events": "事件记录",
    "condition": "条件是否满足",
    "measurements": "测量结果",
    "media": "标注图片或视频",
}


@dataclass(frozen=True)
class OutputSource:
    """A business-named source with only executable result projections."""

    ref: str
    label: str
    kinds: tuple[str, ...]
    media_types: tuple[str, ...]


def result_spec(kind: str, **values: Any) -> ResultSpec:
    """Construct the same result contract as the legacy table API."""
    semantic, shape, projection = RESULT_KIND_SCHEMA[kind]
    return ResultSpec(
        semantic_type=semantic,
        value_shape=shape,
        projection=ResultProjection(kind=projection),
        **values,
    )


def output_sources(
    document: SkillEditorDocument,
    editor: BusinessRuleEditor,
    *,
    result_id: str | None = None,
) -> list[OutputSource]:
    """Inspect lowering without inference, publication or mutating the draft.

    In particular, a branch is not assumed to be boolean and a count condition
    may expose its measurement for a numeric projection. The compiler resolves
    these nodes exactly as it does for real results.
    """
    prepared = editor.prepare(document)
    registry = editor.operators
    values: dict[str, dict[str, CompiledValue]] = {}
    compiled = BusinessRuleCompiler(registry, editor.capabilities).compile_document(
        prepared, source_values=values
    )
    compiled = RuleGraphCompiler(registry).compile_document(compiled)
    template = compiled.skill_template
    sources = editor.source_catalog(prepared)
    known = {s["value"] for s in sources}
    for media, graph in prepared.skill_template.rule_graphs.items():
        for node in graph.nodes:
            ref = f"node:{node.node_id}"
            # Legacy result bindings remain selectable by their business name.
            if (
                node.enabled
                and ref not in known
                and any(spec.source_ref == ref for spec in template.result_specs)
            ):
                sources.append(
                    {"value": ref, "label": f"处理结果 / {node.display_name}"}
                )
                known.add(ref)
    for name, label in _OUTPUT_LABELS.items():
        if any(
            name in v.outputs
            for v in compiled.effective_skill_package.variants.values()
        ):
            sources.append({"value": f"output:{name}", "label": f"输出 / {label}"})
            known.add(f"output:{name}")
    for spec in prepared.skill_template.result_specs:
        if spec.source_ref and spec.source_ref not in known:
            sources.append(
                {
                    "value": spec.source_ref,
                    "label": f"已有结果来源 / {spec.display_name}",
                }
            )
            known.add(spec.source_ref)

    contracts = {
        media: build_runtime_contract(compiled, media)
        for media in compiled.effective_skill_package.variants
        if compiled.effective_skill_package.variants[media].status != "unsupported"
    }
    result = []
    for source in sources:
        ref = source["value"]
        if result_id and source_depends_on_result(prepared, ref, result_id):
            continue
        kinds_by_media: dict[str, set[str]] = {}
        for media, contract in contracts.items():
            variant = compiled.effective_skill_package.variants[media]
            node_types = {
                n.id: contract_type_and_shape(registry.require(n.op).output_type)[0]
                for n in variant.nodes
                if n.enabled
            }
            value = values.get(media, {}).get(ref)
            node = contract["published_sources"].get(ref)
            if ref.startswith("node:"):
                node = ref.split(":", 1)[1]
            if value is None and node not in node_types:
                continue
            accepted = set()
            for kind in RESULT_KIND_SCHEMA:
                spec = result_spec(
                    kind, result_id="type_check", display_name="类型校验"
                )
                projection = spec.projection.kind
                selected = value.result_node(projection) if value else node
                # Event-shaped final outputs bind to the emitted alert, just
                # like build_runtime_contract; the verdict remains boolean.
                if ref.startswith("final:") and projection in {
                    "events",
                    "duration",
                    "stages",
                }:
                    final_output = next(
                        (
                            name
                            for name, bound in contract["output_bindings"].items()
                            if bound == node and name.startswith("final_")
                        ),
                        "",
                    )
                    selected = contract["output_bindings"].get(
                        final_output.replace("final_", "alert_", 1), node
                    )
                if projection_accepts_type(spec, node_types.get(selected, "unknown")):
                    accepted.add(kind)
            kinds_by_media[media] = accepted
        if not kinds_by_media:
            continue
        # Package-global outputs must be compatible in every owning variant.
        kinds = set.intersection(*kinds_by_media.values())
        if kinds:
            media_label = " / ".join(
                "图片" if m == "image" else "视频" for m in kinds_by_media
            )
            result.append(
                OutputSource(
                    ref,
                    f"{source['label']}（{media_label}）",
                    tuple(k for k in RESULT_KIND_SCHEMA if k in kinds),
                    tuple(kinds_by_media),
                )
            )
    counts: dict[str, int] = {}
    unique = []
    for source in result:
        counts[source.label] = counts.get(source.label, 0) + 1
        suffix = f"（同名{counts[source.label]}）" if counts[source.label] > 1 else ""
        unique.append(
            OutputSource(
                source.ref, source.label + suffix, source.kinds, source.media_types
            )
        )
    return unique


def source_depends_on_result(
    document: SkillEditorDocument, ref: str, result_id: str
) -> bool:
    """Reject direct and transitive output/final/event dependency cycles."""
    template = document.skill_template
    visited: set[str] = set()

    def visit(source: str) -> bool:
        if source == f"result:{result_id}":
            return True
        if source in visited:
            return False
        visited.add(source)
        dependencies: list[str] = []
        if source.startswith("final:") and template.final_decision:
            final = template.final_decision
            dependencies = [
                final.source_ref,
                *final.source_refs,
                *(r for refs in final.media_source_refs.values() for r in refs),
            ]
        elif source.startswith("result:"):
            dependencies = [
                s.source_ref
                for s in template.result_specs
                if f"result:{s.result_id}" == source and s.source_ref
            ]
        elif source.startswith("event:"):
            dependencies = [
                s.source_ref
                for p in template.event_patterns
                if f"event:{p.pattern_id}" == source
                for s in p.stages
                if s.source_ref
            ]
        return any(visit(r) for r in dependencies)

    return visit(ref)


def save_output(
    document: SkillEditorDocument,
    editor: BusinessRuleEditor,
    *,
    result_id: str | None,
    display_name: str,
    source_ref: str,
    kind: str,
    unit: str,
    evidence: str,
    save_policy: str,
    show: bool,
) -> tuple[SkillEditorDocument, str]:
    """Change only the selected output, retaining IDs and unexposed policies."""
    from uuid import uuid4

    result = editor.prepare(document)
    sources = {s.ref: s for s in output_sources(result, editor, result_id=result_id)}
    source = sources.get(source_ref)
    if source is None:
        raise BusinessRuleEditError("请选择当前技能中可用的结果来源。")
    if kind not in source.kinds:
        raise BusinessRuleEditError("结果类型与所选来源不兼容，请重新选择结果类型。")
    name = display_name.strip()
    if not name:
        raise BusinessRuleEditError("请填写输出名称。")
    specs = result.skill_template.result_specs
    existing = next((s for s in specs if s.result_id == result_id), None)
    if result_id and existing is None:
        raise BusinessRuleEditError("所选业务输出已不存在，请重新选择。")
    if any(s.display_name == name and s.result_id != result_id for s in specs):
        raise BusinessRuleEditError("业务输出名称不能重复。")
    selected_id = result_id or f"result_{uuid4().hex[:10]}"
    spec = (
        existing.model_copy(deep=True)
        if existing
        else result_spec(kind, result_id=selected_id, display_name=name)
    )
    binding_changed = (
        not existing
        or existing.source_ref != source_ref
        or editor._result_kind(existing) != kind
    )
    spec.display_name = name
    spec.source_ref = source_ref
    spec.unit = unit.strip() or None
    spec.evidence_policy = evidence
    spec.save_policy = save_policy
    if binding_changed:
        replacement = result_spec(kind, result_id=selected_id, display_name=name)
        spec.semantic_type, spec.value_shape, spec.projection = (
            replacement.semantic_type,
            replacement.value_shape,
            replacement.projection,
        )
        spec.media_types = list(source.media_types)
        spec.required_outputs = []
        spec.result_type = None
        spec.empty_policy = "zero" if kind == "count" else "empty"
    spec = ResultSpec.model_validate(spec.model_dump(mode="json"))
    if existing:
        specs[specs.index(existing)] = spec
    else:
        specs.append(spec)
    presentation = next(
        (
            p
            for p in result.skill_template.presentation_specs
            if p.result_id == selected_id
        ),
        None,
    )
    if presentation:
        presentation.show_in_overview = bool(show)
    else:
        result.skill_template.presentation_specs.append(
            PresentationSpec(
                result_id=selected_id,
                show_in_overview=bool(show),
                display_order=len(specs) - 1,
            )
        )
    for branch in result.skill_template.business_branches:
        branch.result_ids = [
            s.result_id for s in specs if s.source_ref == f"branch:{branch.branch_id}"
        ]
    result.version += 1
    return refresh_document_hashes(result), selected_id


def delete_output(
    document: SkillEditorDocument, editor: BusinessRuleEditor, result_id: str
) -> SkillEditorDocument:
    """Delete explicitly, rejecting dangling final-decision dependencies."""
    result = editor.prepare(document)
    specs = result.skill_template.result_specs
    if not any(s.result_id == result_id for s in specs):
        raise BusinessRuleEditError("请先选择已有的业务输出。")
    if len(specs) <= 1:
        raise BusinessRuleEditError("至少需要保留一个业务输出。")
    ref = f"result:{result_id}"
    final = result.skill_template.final_decision
    if final and ref in [
        final.source_ref,
        *final.source_refs,
        *(r for refs in final.media_source_refs.values() for r in refs),
    ]:
        raise BusinessRuleEditError(
            "最终判定仍在使用这个输出，请先修改最终判定的来源。"
        )
    if any(s.source_ref == ref for s in specs if s.result_id != result_id):
        raise BusinessRuleEditError("其它业务输出仍在使用这个输出，请先修改其来源。")
    result.skill_template.result_specs = [s for s in specs if s.result_id != result_id]
    result.skill_template.presentation_specs = [
        p for p in result.skill_template.presentation_specs if p.result_id != result_id
    ]
    for branch in result.skill_template.business_branches:
        branch.result_ids = [i for i in branch.result_ids if i != result_id]
    result.version += 1
    return refresh_document_hashes(result)
