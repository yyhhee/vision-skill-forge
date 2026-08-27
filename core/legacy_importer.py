from __future__ import annotations

from collections import OrderedDict
from hashlib import sha1

from .editor_schema import (
    BusinessBranch,
    CardinalitySpec,
    CompatibilityInfo,
    FinalDecisionSpec,
    ResourceCollection,
    ResourceInstance,
    ResourceRequirement,
    ResultSpec,
    ResolvableValue,
    RuleEdge,
    RuleGraph,
    RuleNode,
    SceneProfile,
    SkillEditorDocument,
    SkillTemplate,
    TriggerPolicy,
)
from .schema import ConfigurationSlot, SkillPackage

_RESULT_TYPES = {
    "objects": "object_list",
    "tracks": "track",
    "events": "event",
    "measurements": "measurement",
    "regions": "measurement",
    "directions": "direction",
    "media": "annotated_media",
}


def _stable_resource_id(*parts: object) -> str:
    value = "|".join(str(part) for part in parts)
    return "res_" + sha1(value.encode("utf-8")).hexdigest()[:24]


def _result_display_name(package: SkillPackage, name: str) -> str:
    fixed = {
        "media": "标注结果",
        "objects": "目标框",
        "tracks": "目标轨迹",
        "events": f"{package.display_name}事件",
        "regions": "场景区域",
        "directions": "参考方向",
    }
    if name in fixed:
        return fixed[name]
    if name.startswith("measurements"):
        for variant in package.variants.values():
            reference = variant.outputs.get(name, "")
            node = next(
                (item for item in variant.nodes if reference == f"${item.id}"),
                None,
            )
            if node is None:
                continue
            if node.op == "measure.region_count@1.0":
                return "各区域目标数量"
            if node.op == "measure.region_speed@1.0":
                return "各区域平均速度"
            if node.op in {"measure.count@1.0", "reduce.count@1.0"}:
                return "目标数量"
            if node.op == "measure.heading@1.0":
                return "运动方向"
        return "测量结果"
    return name.replace("_", " ")


def _result_contract(package: SkillPackage, name: str) -> dict:
    if name == "objects":
        return {"semantic_type": "entity_set", "value_shape": "list", "projection": {"kind": "entities"}}
    if name == "tracks":
        return {"semantic_type": "track_set", "value_shape": "list", "projection": {"kind": "tracks"}}
    if name == "events":
        return {"semantic_type": "event_set", "value_shape": "list", "projection": {"kind": "events"}}
    if name == "media":
        return {"semantic_type": "media", "value_shape": "single", "projection": {"kind": "media"}}
    if name in {"regions", "directions"}:
        return {"semantic_type": "resource", "value_shape": "list", "projection": {"kind": "resource"}}
    if name.startswith("measurements"):
        node = next(
            (
                item
                for variant in package.variants.values()
                for item in variant.nodes
                if variant.outputs.get(name) == f"${item.id}"
            ),
            None,
        )
        if node is not None and node.op in {
            "measure.region_count@1.0",
            "measure.region_speed@1.0",
        }:
            return {
                "semantic_type": "scalar",
                "value_shape": "series",
                "projection": {"kind": "identity"},
                "grouping": ["key"],
                "unit": "像素/秒" if node.op == "measure.region_speed@1.0" else None,
            }
    return {"semantic_type": "scalar", "value_shape": "single", "projection": {"kind": "value"}}


def _result_specs(package: SkillPackage) -> list[ResultSpec]:
    names: OrderedDict[str, list[str]] = OrderedDict()
    for media_type, variant in package.variants.items():
        for name in variant.outputs:
            names.setdefault(name, []).append(media_type)
    return [
        ResultSpec(
            result_id=f"result_{name}",
            display_name=_result_display_name(package, name),
            source_ref=f"output:{name}",
            media_types=media_types,
            required_outputs=[name],
            evidence_policy="required" if name == "events" else "optional",
            **_result_contract(package, name),
        )
        for name, media_types in names.items()
    ]


def _requirement(media_type: str, slot: ConfigurationSlot) -> ResourceRequirement:
    requirement_id = f"{media_type}_{slot.slot_id}"
    source_id = (
        f"{media_type}_{slot.key_source_slot_id}"
        if slot.key_source_slot_id
        else None
    )
    if slot.kind in {"region_set", "direction_set"}:
        cardinality = (
            CardinalitySpec(mode="match_collection", source_requirement_id=source_id)
            if source_id
            else CardinalitySpec(mode="dynamic", minimum=slot.minimum_items)
        )
    else:
        cardinality = CardinalitySpec(mode="exact", exact=1, minimum=1, maximum=1)
    role = "lane_reference_direction" if slot.kind.startswith("direction") else "region"
    resource_type = {
        "region": "region",
        "region_set": "region_collection",
        "direction": "direction",
        "direction_set": "direction_collection",
    }[slot.kind]
    return ResourceRequirement(
        requirement_id=requirement_id,
        resource_type=resource_type,
        display_name=slot.label,
        semantic_role=role,
        cardinality=cardinality,
        binding_policy="for_each" if slot.kind.endswith("_set") else "direct",
        allowed_shapes=slot.allowed_shapes,
        pairing_policy="one_per_region" if source_id else "none",
        required_before="run" if slot.required else "never",
        media_types=[media_type],
        legacy_metadata={
            "slot_id": slot.slot_id,
            "node_id": slot.binding.node_id,
            "parameter": slot.binding.parameter,
        },
    )


def _configured_resources(
    package: SkillPackage, requirements: list[ResourceRequirement]
) -> SceneProfile | None:
    profile = SceneProfile(display_name="导入的场景配置")
    requirements_by_id = {item.requirement_id: item for item in requirements}
    old_to_new: dict[tuple[str, str, str], str] = {}
    for media_type, variant in package.variants.items():
        nodes = {node.id: node for node in variant.nodes}
        for slot in variant.configuration_slots:
            requirement_id = f"{media_type}_{slot.slot_id}"
            requirement = requirements_by_id[requirement_id]
            node = nodes.get(slot.binding.node_id)
            if node is None:
                continue
            collection = ResourceCollection(requirement_id=requirement_id)
            if slot.kind == "region" and node.params.get("points"):
                instance = ResourceInstance(
                    resource_id=_stable_resource_id(media_type, slot.slot_id, "single"),
                    resource_type="region",
                    display_name=slot.label,
                    semantic_role=requirement.semantic_role,
                    geometry={
                        "shape": node.params.get("shape"),
                        "points": node.params.get("points"),
                    },
                )
                collection.items.append(instance)
            elif slot.kind == "region_set":
                for index, item in enumerate(node.params.get("regions", []), start=1):
                    instance = ResourceInstance(
                        resource_id=_stable_resource_id(
                            media_type, slot.slot_id, item.get("id", index)
                        ),
                        resource_type="region",
                        display_name=item.get("label") or f"区域{index}",
                        semantic_role=requirement.semantic_role,
                        geometry={"shape": item.get("shape"), "points": item.get("points")},
                        legacy_metadata={"legacy_id": item.get("id")},
                    )
                    collection.items.append(instance)
                    if item.get("id"):
                        old_to_new[(media_type, slot.slot_id, item["id"])] = instance.resource_id
            elif slot.kind == "direction" and node.params.get("vector"):
                collection.items.append(
                    ResourceInstance(
                        resource_id=_stable_resource_id(media_type, slot.slot_id, "single"),
                        resource_type="direction",
                        display_name=slot.label,
                        semantic_role=requirement.semantic_role,
                        geometry={key: node.params.get(key) for key in ("vector", "start", "end")},
                    )
                )
            elif slot.kind == "direction_set":
                for index, item in enumerate(node.params.get("directions", []), start=1):
                    source_slot = slot.key_source_slot_id or ""
                    collection.items.append(
                        ResourceInstance(
                            resource_id=_stable_resource_id(
                                media_type, slot.slot_id, item.get("key", index)
                            ),
                            resource_type="direction",
                            display_name=f"方向{index}",
                            semantic_role=requirement.semantic_role,
                            geometry={key: item.get(key) for key in ("vector", "start", "end")},
                            paired_resource_id=old_to_new.get(
                                (media_type, source_slot, item.get("key", ""))
                            ),
                            legacy_metadata={"legacy_key": item.get("key")},
                        )
                    )
            if collection.items:
                collection.completed = True
                profile.collections.append(collection)
    return profile if profile.collections else None


def _node_kind(operator: str) -> str:
    prefix = operator.split(".", 1)[0]
    return {
        "rex": "target",
        "objects": "target",
        "track": "target",
        "visual": "attribute",
        "spatial": "relation",
        "pairs": "relation",
        "region": "region",
        "regions": "region",
        "measure": "aggregate",
        "reduce": "aggregate",
        "logic": "logic_group",
        "filter": "condition",
        "state": "condition",
        "temporal": "temporal_qualifier",
        "event": "temporal_qualifier",
        "output": "output",
    }.get(prefix, "scope")


def _rule_graph(package: SkillPackage, media_type: str) -> RuleGraph:
    variant = package.variants[media_type]
    slots_by_node: dict[str, list] = {}
    for slot in variant.configuration_slots:
        slots_by_node.setdefault(slot.binding.node_id, []).append(slot)
    output_names: dict[str, list[str]] = {}
    for name, reference in variant.outputs.items():
        if reference.startswith("$"):
            output_names.setdefault(reference[1:], []).append(name)
    atom_ids = {}
    for atom_id, node_ids in variant.atom_bindings.items():
        for node_id in node_ids:
            atom_ids.setdefault(node_id, []).append(atom_id)
    node_ids = {node.id for node in variant.nodes}
    edges = []
    rule_nodes = []
    for node in variant.nodes:
        bindings = {}
        for port, reference in node.inputs.items():
            references = [reference] if isinstance(reference, str) else reference
            external = []
            for item in references:
                if item.startswith("$") and item[1:] in node_ids:
                    edges.append(RuleEdge(source=item[1:], target=node.id, port=port))
                else:
                    external.append(item)
            if external:
                bindings[port] = external[0] if isinstance(reference, str) else external
        rule_nodes.append(
            RuleNode(
                node_id=node.id,
                kind=_node_kind(node.op),
                display_name=node.id,
                operator=node.op,
                input_bindings=bindings,
                semantic_atom_ids=atom_ids.get(node.id, []),
                output_name=(output_names.get(node.id) or [None])[0],
                output_names=output_names.get(node.id, [])[1:],
                params=node.params,
                parameter_sources={
                    name: ResolvableValue(
                        state="explicit",
                        value=value,
                        source="legacy_skill_package",
                        required_before="never",
                    )
                    for name, value in node.params.items()
                    if value is not None
                },
                configuration_slots=slots_by_node.get(node.id, []),
                enabled=node.enabled,
            )
        )
    return RuleGraph(nodes=rule_nodes, edges=edges)


def _primary_output_node(graph: RuleGraph) -> RuleNode | None:
    output_nodes = [node for node in graph.nodes if node.output_name]
    for preferred in ("events", "objects", "tracks"):
        match = next(
            (
                node
                for node in output_nodes
                if preferred in [node.output_name, *node.output_names]
            ),
            None,
        )
        if match is not None:
            return match
    measurement = next(
        (
            node
            for node in output_nodes
            if any(
                name and name.startswith("measurements")
                for name in [node.output_name, *node.output_names]
            )
        ),
        None,
    )
    if measurement is not None:
        return measurement
    if output_nodes:
        return output_nodes[0]
    if graph.nodes:
        sources = {edge.source for edge in graph.edges}
        return next(
            (node for node in graph.nodes if node.node_id not in sources),
            graph.nodes[-1],
        )
    return None


def _business_branches(
    package: SkillPackage, graphs: dict[str, RuleGraph]
) -> list[BusinessBranch]:
    branches = []
    for media_type, graph in graphs.items():
        root = _primary_output_node(graph)
        if root is None:
            continue
        ancestors = {root.node_id}
        changed = True
        while changed:
            changed = False
            for edge in graph.edges:
                if edge.target in ancestors and edge.source not in ancestors:
                    ancestors.add(edge.source)
                    changed = True
        branches.append(
            BusinessBranch(
                branch_id=f"{media_type}_main",
                display_name=package.display_name,
                description=(
                    "由当前已验证执行流程导入；可调整组成步骤参数，"
                    "也可继续添加通用业务条件进行组合。"
                ),
                media_type=media_type,
                node_ids=[node.node_id for node in graph.nodes if node.node_id in ancestors],
                root_node_id=root.node_id,
                evidence_policy="required",
            )
        )
    return branches


def _final_decision(
    package: SkillPackage, result_specs: list[ResultSpec]
) -> FinalDecisionSpec | None:
    by_output = {
        output: spec
        for spec in result_specs
        for output in spec.required_outputs
    }
    media_sources: dict[str, list[str]] = {}
    for media_type, variant in package.variants.items():
        selected = next(
            (
                output
                for output in ("events", "objects", "tracks")
                if output in variant.outputs
            ),
            None,
        )
        if selected is None:
            selected = next(iter(variant.outputs), None)
        if selected and selected in by_output:
            media_sources[media_type] = [f"result:{by_output[selected].result_id}"]
    sources = list(dict.fromkeys(
        source for items in media_sources.values() for source in items
    ))
    if not sources:
        return None
    all_events = all(
        source == "result:result_events" for source in sources
    )
    return FinalDecisionSpec(
        display_name=f"{package.display_name}结果",
        decision_type="event_decision" if all_events else "detection_summary",
        source_ref=sources[0],
        source_refs=sources,
        media_source_refs=media_sources,
        combination="AND",
    )


def import_skill_package(package: SkillPackage) -> SkillEditorDocument:
    requirements = [
        _requirement(media_type, slot)
        for media_type, variant in package.variants.items()
        for slot in variant.configuration_slots
    ]
    profile = _configured_resources(package, requirements)
    graphs = {
        media_type: _rule_graph(package, media_type)
        for media_type in package.input.accept
    }
    result_specs = _result_specs(package)
    preferred_media = "video" if "video" in graphs else next(iter(graphs))
    template = SkillTemplate(
        skill_id=package.skill_id,
        display_name=package.display_name,
        original_instruction=package.original_instruction,
        source_type="legacy",
        semantic_ir=package.semantic_ir,
        result_specs=result_specs,
        final_decision=_final_decision(package, result_specs),
        trigger_policy=TriggerPolicy(
            mode="once" if any("events" in item.outputs for item in package.variants.values()) else "none",
            outputs=["event_record", "annotated_media"],
        ),
        rule_graph=graphs[preferred_media],
        rule_graphs=graphs,
        business_branches=_business_branches(package, graphs),
        resource_requirements=requirements,
    )
    return SkillEditorDocument(
        schema_version="3.0",
        version=package.version,
        skill_template=template,
        scene_profiles=[profile] if profile else [],
        active_scene_profile_id=profile.scene_profile_id if profile else None,
        atomic_plan={
            media_type: variant.model_dump(mode="json")
            for media_type, variant in package.variants.items()
        },
        effective_skill_package=package,
        compatibility=CompatibilityInfo(
            editability="legacy_atomic_only",
            issues=["旧版SkillPackage未包含可逆RuleGraph，已保留原子执行计划"],
        ),
    )


__all__ = ["import_skill_package"]
