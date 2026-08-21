from __future__ import annotations

from collections import deque
import math
from typing import Any

from .registry import OperatorDefinition, OperatorRegistry, ParameterSpec
from .schema import SkillPackage, VisualSkillSpec


_TYPE_GROUPS = {
    "EntitySet": {"ObjectSet", "TrackSet", "EntitySet"},
    "ValueSet": {"ScalarSet", "VectorSet", "ConditionSet", "ValueSet"},
    "CountableSet": {
        "ObjectSet", "TrackSet", "EventSet", "PairSet", "ScopedSet", "EntitySet"
    },
}


def _refs(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else value


def _compatible(actual: str, expected: str) -> bool:
    return actual == expected or actual in _TYPE_GROUPS.get(expected, set())


def _value_matches(value: Any, spec: ParameterSpec) -> bool:
    def target_list(item):
        return (
            isinstance(item, list)
            and bool(item)
            and all(
                isinstance(target, dict)
                and isinstance(target.get("label"), str)
                and bool(target["label"])
                and isinstance(target.get("phrases"), list)
                and bool(target["phrases"])
                and all(isinstance(phrase, str) and bool(phrase) for phrase in target["phrases"])
                for target in item
            )
        )

    def point_list(item):
        return (
            isinstance(item, list)
            and bool(item)
            and all(
                isinstance(point, list)
                and len(point) == 2
                and all(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1 for value in point)
                for point in item
            )
        )

    def vector2(item):
        return (
            isinstance(item, list)
            and len(item) == 2
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in item)
            and any(value != 0 for value in item)
        )

    def normalized_point(item):
        return (
            isinstance(item, list)
            and len(item) == 2
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0 <= value <= 1
                for value in item
            )
        )

    def normalized_box(item):
        return (
            isinstance(item, list)
            and len(item) == 4
            and all(isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1 for value in item)
            and item[0] < item[2]
            and item[1] < item[3]
        )

    def relative_box(item):
        return (
            isinstance(item, list)
            and len(item) == 4
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for value in item
            )
            and item[0] < item[2]
            and item[1] < item[3]
        )

    def string_list(item):
        return (
            isinstance(item, list)
            and len(item) >= 2
            and all(isinstance(value, str) and bool(value) for value in item)
        )

    def nonempty_string_list(item):
        return (
            isinstance(item, list)
            and bool(item)
            and all(isinstance(value, str) and bool(value) for value in item)
        )

    def named_region_list(item):
        return (
            isinstance(item, list)
            and all(
                isinstance(region, dict)
                and isinstance(region.get("id"), str)
                and bool(region["id"])
                and region.get("shape") in {"rectangle", "polygon"}
                and point_list(region.get("points"))
                and (
                    (region["shape"] == "rectangle" and len(region["points"]) == 2)
                    or (region["shape"] == "polygon" and len(region["points"]) >= 3)
                )
                for region in item
            )
        )

    def direction_list(item):
        return (
            isinstance(item, list)
            and all(
                isinstance(direction, dict)
                and isinstance(direction.get("key"), str)
                and bool(direction["key"])
                and vector2(direction.get("vector"))
                and (
                    ("start" not in direction and "end" not in direction)
                    or (
                        normalized_point(direction.get("start"))
                        and normalized_point(direction.get("end"))
                        and direction["start"] != direction["end"]
                    )
                )
                for direction in item
            )
        )

    def numeric_mapping(item):
        return (
            isinstance(item, dict)
            and all(
                isinstance(key, str)
                and bool(key)
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                for key, value in item.items()
            )
        )

    def string_mapping(item):
        return (
            isinstance(item, dict)
            and all(
                isinstance(key, str)
                and bool(key)
                and isinstance(value, str)
                and bool(value)
                for key, value in item.items()
            )
        )

    kinds = {
        "string": lambda item: isinstance(item, str),
        "string_or_null": lambda item: item is None or isinstance(item, str),
        "number": lambda item: isinstance(item, (int, float)) and not isinstance(item, bool),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "number_or_null": lambda item: item is None or (isinstance(item, (int, float)) and not isinstance(item, bool)),
        "integer_or_null": lambda item: item is None or (isinstance(item, int) and not isinstance(item, bool)),
        "boolean": lambda item: isinstance(item, bool),
        "target_list": target_list,
        "point_list": point_list,
        "point_or_null": lambda item: item is None or normalized_point(item),
        "vector2": vector2,
        "normalized_box": normalized_box,
        "relative_box": relative_box,
        "string_list": string_list,
        "nonempty_string_list": nonempty_string_list,
        "named_region_list": named_region_list,
        "direction_list": direction_list,
        "numeric_mapping": numeric_mapping,
        "string_mapping": string_mapping,
    }
    checker = kinds.get(spec.kind)
    return True if checker is None else checker(value)


def _validate_params(
    node_id: str, definition: OperatorDefinition, params: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    known = set(definition.defaults) | set(definition.parameters)
    for name in params:
        if name not in known:
            errors.append(f"node {node_id}: unknown parameter {name}")
    for name, parameter in definition.parameters.items():
        if parameter.required and name not in params:
            errors.append(f"node {node_id}: missing required parameter {name}")
            continue
        if name not in params:
            continue
        value = params[name]
        if not _value_matches(value, parameter):
            errors.append(f"node {node_id}: invalid type for parameter {name}")
            continue
        if parameter.choices and value not in parameter.choices:
            errors.append(f"node {node_id}: invalid value for parameter {name}")
        if value is not None and isinstance(value, (int, float)) and not isinstance(value, bool):
            if parameter.minimum is not None and value < parameter.minimum:
                errors.append(f"node {node_id}: parameter {name} below minimum")
            if parameter.maximum is not None and value > parameter.maximum:
                errors.append(f"node {node_id}: parameter {name} above maximum")
    if definition.op == "direction.manual@1.0":
        has_start = params.get("start") is not None
        has_end = params.get("end") is not None
        if has_start != has_end:
            errors.append(
                f"node {node_id}: direction start and end must be provided together"
            )
        elif has_start and params["start"] == params["end"]:
            errors.append(f"node {node_id}: direction start and end cannot be equal")
    if definition.op == "output.draw@1.0":
        if params.get("output_size_mode") == "fixed" and (
            params.get("output_width") is None
            or params.get("output_height") is None
        ):
            errors.append(
                f"node {node_id}: fixed output size requires width and height"
            )
        if (
            params.get("output_fps_mode") == "fixed"
            and params.get("output_fps") is None
        ):
            errors.append(f"node {node_id}: fixed output FPS requires output_fps")
    return errors


def validate_skill(spec: VisualSkillSpec, registry: OperatorRegistry) -> list[str]:
    errors: list[str] = []
    enabled_nodes = [node for node in spec.nodes if node.enabled]
    ids = [node.id for node in enabled_nodes]
    duplicate_ids = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    for node_id in duplicate_ids:
        errors.append(f"duplicate node id: {node_id}")

    node_by_id = {node.id: node for node in enabled_nodes}
    output_types: dict[str, str] = {}
    definitions: dict[str, OperatorDefinition] = {}
    dependencies: dict[str, set[str]] = {node.id: set() for node in enabled_nodes}

    for node in enabled_nodes:
        definition = registry.get(node.op)
        if definition is None:
            errors.append(f"node {node.id}: unknown operator {node.op}")
            continue
        definitions[node.id] = definition
        output_types[node.id] = definition.output_type
        errors.extend(_validate_params(node.id, definition, node.params))

        if node.op in {"logic.all@1.0", "logic.any@1.0"}:
            condition_refs = node.inputs.get("conditions")
            if not isinstance(condition_refs, list) or len(condition_refs) < 2:
                errors.append(
                    f"node {node.id}: {node.op} requires at least two condition references"
                )
        if node.op in {"objects.merge@1.0", "regions.merge@1.0"}:
            input_name = "objects" if node.op == "objects.merge@1.0" else "regions"
            references = node.inputs.get(input_name)
            if not isinstance(references, list) or len(references) < 2:
                errors.append(
                    f"node {node.id}: {node.op} requires at least two {input_name} references"
                )
        if node.op == "measure.count@1.0":
            supplied = {name for name in ("entities", "objects") if name in node.inputs}
            if len(supplied) != 1:
                errors.append(
                    f"node {node.id}: measure.count requires exactly one of entities or objects"
                )

        required_inputs = set(definition.input_types) - set(definition.optional_inputs)
        missing_inputs = required_inputs - set(node.inputs)
        for name in sorted(missing_inputs):
            errors.append(f"node {node.id}: missing required input {name}")
        for name in node.inputs:
            if name not in definition.input_types:
                errors.append(f"node {node.id}: unknown input {name}")

        for value in node.inputs.values():
            for ref in _refs(value):
                if not isinstance(ref, str) or not ref.startswith("$"):
                    errors.append(f"node {node.id}: input reference must start with $")
                    continue
                ref_id = ref[1:]
                if ref_id == "input":
                    continue
                if ref_id not in node_by_id:
                    errors.append(f"node {node.id}: unknown reference {ref}")
                    continue
                dependencies[node.id].add(ref_id)

    indegree = {node_id: len(deps) for node_id, deps in dependencies.items()}
    reverse: dict[str, set[str]] = {node_id: set() for node_id in dependencies}
    for node_id, deps in dependencies.items():
        for dep in deps:
            reverse.setdefault(dep, set()).add(node_id)
    queue = deque(sorted(node_id for node_id, degree in indegree.items() if degree == 0))
    visited: list[str] = []
    while queue:
        current = queue.popleft()
        visited.append(current)
        for dependent in sorted(reverse.get(current, ())):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                queue.append(dependent)
    if len(visited) != len(dependencies):
        cycle_nodes = sorted(set(dependencies) - set(visited))
        errors.append(f"cycle detected involving: {', '.join(cycle_nodes)}")

    for node in enabled_nodes:
        definition = definitions.get(node.id)
        if definition is None:
            continue
        for input_name, value in node.inputs.items():
            expected = definition.input_types.get(input_name)
            if expected is None:
                continue
            for ref in _refs(value):
                ref_id = ref[1:] if isinstance(ref, str) and ref.startswith("$") else ""
                actual = "Media" if ref_id == "input" else output_types.get(ref_id)
                if actual is not None and not _compatible(actual, expected):
                    errors.append(
                        f"node {node.id}: type mismatch for {input_name}; "
                        f"expected {expected}, got {actual} from {ref}"
                    )

    for output_name, ref in spec.outputs.items():
        if not ref.startswith("$"):
            errors.append(f"output {output_name}: reference must start with $")
        elif ref[1:] not in node_by_id:
            errors.append(f"output {output_name}: unknown reference {ref}")

    output_node_ids = {
        ref[1:] for ref in spec.outputs.values()
        if ref.startswith("$") and ref[1:] in node_by_id
    }
    output_ancestors = set(output_node_ids)
    pending = list(output_node_ids)
    while pending:
        current = pending.pop()
        for dependency in dependencies.get(current, set()):
            if dependency not in output_ancestors:
                output_ancestors.add(dependency)
                pending.append(dependency)
    for node in enabled_nodes:
        if node.id not in output_ancestors:
            errors.append(f"node {node.id}: cannot reach any declared output")

    if "video" in spec.input.accept and not any(
        node.op.startswith("video.sample@") for node in enabled_nodes
    ):
        errors.append(
            "video skill requires explicit video.sample@1.0 or later operator"
        )

    return errors


def assert_valid_skill(spec: VisualSkillSpec, registry: OperatorRegistry) -> None:
    errors = validate_skill(spec, registry)
    if errors:
        raise ValueError("\n".join(errors))


def validate_skill_package(
    package: SkillPackage, registry: OperatorRegistry
) -> list[str]:
    errors: list[str] = []
    if package.compile_status == "compiled" and package.semantic_ir.unresolved:
        errors.append("compiled package cannot contain unresolved semantics")
    for media_type in package.input.accept:
        variant = package.variants[media_type]
        node_ids = {node.id for node in variant.nodes if node.enabled}
        for constraint in package.semantic_ir.constraints:
            atom_id = constraint.atom_id
            bound = variant.atom_bindings.get(atom_id or "")
            if not bound:
                errors.append(
                    f"{media_type}: semantic atom {atom_id} is not bound to workflow nodes"
                )
                continue
            for node_id in bound:
                if node_id not in node_ids:
                    errors.append(
                        f"{media_type}: semantic atom {atom_id} binds unknown node {node_id}"
                    )
        spec = VisualSkillSpec.model_validate(
            {
                "version": "0.1",
                "name": package.skill_id,
                "display_name": package.display_name,
                "original_instruction": package.original_instruction,
                "compile_status": "degraded"
                if package.compile_status == "degraded"
                else "compiled",
                "input": {"accept": [media_type]},
                "nodes": [node.model_dump(mode="json") for node in variant.nodes],
                "outputs": dict(variant.outputs),
            }
        )
        pending_parameters = {
            (slot.binding.node_id, slot.binding.parameter)
            for slot in variant.configuration_slots
            if variant.status == "needs_configuration"
        }
        for error in validate_skill(spec, registry):
            if any(
                error in {
                    f"node {node_id}: invalid type for parameter {parameter}",
                    f"node {node_id}: missing required parameter {parameter}",
                }
                for node_id, parameter in pending_parameters
            ):
                continue
            if error.startswith("node "):
                errors.append(f"{media_type}/{error[5:]}")
            else:
                errors.append(f"{media_type}: {error}")
    return errors


def validate_executable_skill_package(
    package: SkillPackage,
    registry: OperatorRegistry,
    media_type: str | None = None,
) -> list[str]:
    errors = validate_skill_package(package, registry)
    from .configuration import pending_required_slots

    errors.extend(
        f"{item['media_type']}: required configuration slot "
        f"{item['slot_id']} is pending"
        for item in pending_required_slots(package)
        if media_type is None or item["media_type"] == media_type
    )
    return errors


def assert_executable_skill_package(
    package: SkillPackage,
    registry: OperatorRegistry,
    media_type: str | None = None,
) -> None:
    errors = validate_executable_skill_package(package, registry, media_type)
    if errors:
        raise ValueError("\n".join(errors))


def assert_valid_skill_package(
    package: SkillPackage, registry: OperatorRegistry
) -> None:
    errors = validate_skill_package(package, registry)
    if errors:
        raise ValueError("\n".join(errors))


__all__ = [
    "assert_valid_skill",
    "assert_valid_skill_package",
    "validate_skill",
    "validate_skill_package",
]
