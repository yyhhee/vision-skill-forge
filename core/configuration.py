from __future__ import annotations

from copy import deepcopy
from typing import Any

from .registry import OperatorRegistry
from .schema import ConfigurationSlot, SkillNode, SkillPackage, WorkflowVariant


def _valid_points(shape: str, points: Any) -> bool:
    if not isinstance(points, list):
        return False
    expected = 2 if shape == "rectangle" else 3
    if (shape == "rectangle" and len(points) != expected) or (
        shape == "polygon" and len(points) < expected
    ):
        return False
    return all(
        isinstance(point, list)
        and len(point) == 2
        and all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and 0.0 <= value <= 1.0
            for value in point
        )
        for point in points
    )


def _direction_vector(
    start: list[float], end: list[float]
) -> list[float]:
    endpoints = [start, end]
    if any(
        not isinstance(point, list)
        or len(point) != 2
        or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or value < 0.0
            or value > 1.0
            for value in point
        )
        for point in endpoints
    ):
        raise ValueError("direction endpoints must be normalized coordinate pairs")
    vector = [
        float(end[0]) - float(start[0]),
        float(end[1]) - float(start[1]),
    ]
    if not any(value != 0 for value in vector):
        raise ValueError("direction endpoints cannot be equal")
    return vector


def _slot_active(slot: ConfigurationSlot, node: SkillNode | None) -> bool:
    return (
        node is not None
        and (slot.active_when_op is None or node.op in slot.active_when_op)
    )


def _allowed_region_shapes(slot: ConfigurationSlot | dict[str, Any]) -> list[str]:
    shapes = (
        slot.allowed_shapes
        if isinstance(slot, ConfigurationSlot)
        else slot.get("allowed_shapes", [])
    )
    return list(shapes or ["rectangle", "polygon"])


def _slot_configured(slot: ConfigurationSlot, node: SkillNode | None) -> bool:
    if not _slot_active(slot, node) or node is None:
        return True
    if slot.kind == "region":
        shape = node.params.get("shape")
        return shape in _allowed_region_shapes(slot) and _valid_points(
            shape, node.params.get("points")
        )
    if slot.kind == "region_set":
        regions = node.params.get("regions")
        return (
            isinstance(regions, list)
            and len(regions) >= slot.minimum_items
            and all(
                isinstance(item, dict)
                and bool(item.get("id"))
                and item.get("shape") in _allowed_region_shapes(slot)
                and _valid_points(item.get("shape"), item.get("points"))
                for item in regions
            )
            and len({item["id"] for item in regions}) == len(regions)
        )
    if slot.kind == "direction":
        vector = node.params.get("vector")
        return (
            isinstance(vector, list)
            and len(vector) == 2
            and all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in vector
            )
            and any(value != 0 for value in vector)
        )
    directions = node.params.get("directions")
    return (
        isinstance(directions, list)
        and len(directions) >= slot.minimum_items
        and all(
            isinstance(item, dict)
            and bool(item.get("key"))
            and isinstance(item.get("vector"), list)
            and len(item["vector"]) == 2
            and any(value != 0 for value in item["vector"])
            for item in directions
        )
        and len({item["key"] for item in directions}) == len(directions)
    )


def configuration_status(package: SkillPackage) -> list[dict[str, Any]]:
    result = []
    for media_type, variant in package.variants.items():
        nodes = {node.id: node for node in variant.nodes}
        slots = {slot.slot_id: slot for slot in variant.configuration_slots}
        for slot in variant.configuration_slots:
            node = nodes.get(slot.binding.node_id)
            configured = _slot_configured(slot, node)
            if (
                configured
                and _slot_active(slot, node)
                and slot.key_source_slot_id is not None
            ):
                source_slot = slots.get(slot.key_source_slot_id)
                source_node = (
                    nodes.get(source_slot.binding.node_id)
                    if source_slot is not None
                    else None
                )
                expected_keys = {
                    item.get("id")
                    for item in (
                        source_node.params.get("regions", [])
                        if source_node is not None
                        else []
                    )
                    if isinstance(item, dict) and item.get("id")
                }
                actual_keys = {
                    item.get("key")
                    for item in (node.params.get("directions", []) if node else [])
                    if isinstance(item, dict) and item.get("key")
                }
                configured = bool(expected_keys) and actual_keys == expected_keys
            result.append(
                {
                    "media_type": media_type,
                    "slot_id": slot.slot_id,
                    "label": slot.label,
                    "kind": slot.kind,
                    "required": slot.required,
                    "active": _slot_active(slot, node),
                    "configured": configured,
                    "node_id": slot.binding.node_id,
                }
            )
    return result


def pending_required_slots(package: SkillPackage) -> list[dict[str, Any]]:
    return [
        item
        for item in configuration_status(package)
        if item["active"] and item["required"] and not item["configured"]
    ]


def _refresh_states(data: dict[str, Any]) -> None:
    probe = SkillPackage.model_validate(data)
    pending_by_media = {
        item["media_type"] for item in pending_required_slots(probe)
    }
    for media_type, variant in data["variants"].items():
        if variant["status"] == "unsupported":
            continue
        variant["status"] = (
            "needs_configuration"
            if media_type in pending_by_media
            else "executable"
        )
    data["compile_status"] = (
        "needs_review"
        if pending_by_media or data.get("compatibility_issues")
        else "compiled"
    )


class ConfigurationBinder:
    def __init__(self, registry: OperatorRegistry):
        self.registry = registry

    @staticmethod
    def _locate(
        data: dict[str, Any], media_type: str, slot_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        variant = data.get("variants", {}).get(media_type)
        if variant is None or variant.get("status") == "unsupported":
            raise ValueError(f"skill has no configurable {media_type} variant")
        slot = next(
            (
                item
                for item in variant.get("configuration_slots", [])
                if item["slot_id"] == slot_id
            ),
            None,
        )
        if slot is None:
            raise ValueError(f"unknown configuration slot: {slot_id}")
        node = next(
            (
                item
                for item in variant["nodes"]
                if item["id"] == slot["binding"]["node_id"]
            ),
            None,
        )
        if node is None:
            raise ValueError(f"configuration node does not exist: {slot_id}")
        return slot, node

    def bind_region(
        self,
        package: SkillPackage,
        *,
        media_type: str,
        slot_id: str,
        shape: str,
        points: list[list[float]],
    ) -> SkillPackage:
        data = deepcopy(package.model_dump(mode="json"))
        slot, node = self._locate(data, media_type, slot_id)
        if slot["kind"] != "region":
            raise ValueError(f"slot {slot_id} is not a single region")
        if shape not in _allowed_region_shapes(slot):
            raise ValueError(f"shape {shape} is not allowed for slot {slot_id}")
        if not _valid_points(shape, points):
            raise ValueError(f"invalid {shape} points for slot {slot_id}")
        node.update(
            {
                "op": "region.manual@1.0",
                "inputs": {},
                "params": {"shape": shape, "points": points},
            }
        )
        return self._finish_draft(data)

    def bind_named_region(
        self,
        package: SkillPackage,
        *,
        media_type: str,
        slot_id: str,
        region_id: str,
        label: str,
        shape: str,
        points: list[list[float]],
    ) -> SkillPackage:
        data = deepcopy(package.model_dump(mode="json"))
        slot, node = self._locate(data, media_type, slot_id)
        if slot["kind"] != "region_set":
            raise ValueError(f"slot {slot_id} is not a named region set")
        key = region_id.strip()
        if not key:
            raise ValueError("region_id cannot be empty")
        if shape not in _allowed_region_shapes(slot):
            raise ValueError(f"shape {shape} is not allowed for slot {slot_id}")
        if not _valid_points(shape, points):
            raise ValueError(f"invalid {shape} points for slot {slot_id}")
        regions = list(node.get("params", {}).get("regions", []))
        replacement = {
            "id": key,
            "label": label.strip() or key,
            "shape": shape,
            "points": points,
        }
        index = next(
            (i for i, item in enumerate(regions) if item.get("id") == key),
            None,
        )
        if index is None:
            regions.append(replacement)
        else:
            regions[index] = replacement
        node.update(
            {
                "op": "region.manual_set@1.0",
                "inputs": {},
                "params": {"regions": regions},
            }
        )
        return self._finish_draft(data)

    def delete_named_region(
        self,
        package: SkillPackage,
        *,
        media_type: str,
        slot_id: str,
        region_id: str,
    ) -> SkillPackage:
        data = deepcopy(package.model_dump(mode="json"))
        slot, node = self._locate(data, media_type, slot_id)
        if slot["kind"] != "region_set":
            raise ValueError(f"slot {slot_id} is not a named region set")
        regions = list(node.get("params", {}).get("regions", []))
        remaining = [item for item in regions if item.get("id") != region_id]
        if len(remaining) == len(regions):
            raise ValueError(f"unknown named region: {region_id}")
        node["params"] = {"regions": remaining}
        variant = data["variants"][media_type]
        for dependent_slot in variant.get("configuration_slots", []):
            if dependent_slot.get("key_source_slot_id") != slot_id:
                continue
            dependent_node = next(
                (
                    item
                    for item in variant["nodes"]
                    if item["id"] == dependent_slot["binding"]["node_id"]
                ),
                None,
            )
            if (
                dependent_node is not None
                and dependent_node.get("op") == "direction.manual_set@1.0"
            ):
                directions = dependent_node.get("params", {}).get("directions", [])
                dependent_node["params"] = {
                    "directions": [
                        item
                        for item in directions
                        if item.get("key") != region_id
                    ]
                }
        return self._finish_draft(data)

    def delete_named_direction(
        self,
        package: SkillPackage,
        *,
        media_type: str,
        slot_id: str,
        key: str,
    ) -> SkillPackage:
        data = deepcopy(package.model_dump(mode="json"))
        slot, node = self._locate(data, media_type, slot_id)
        if slot["kind"] != "direction_set":
            raise ValueError(f"slot {slot_id} is not a named direction set")
        directions = list(node.get("params", {}).get("directions", []))
        remaining = [item for item in directions if item.get("key") != key]
        if len(remaining) == len(directions):
            raise ValueError(f"unknown named direction: {key}")
        node["params"] = {"directions": remaining}
        return self._finish_draft(data)

    def bind_named_direction(
        self,
        package: SkillPackage,
        *,
        media_type: str,
        slot_id: str,
        key: str,
        start: list[float],
        end: list[float],
    ) -> SkillPackage:
        data = deepcopy(package.model_dump(mode="json"))
        slot, node = self._locate(data, media_type, slot_id)
        if slot["kind"] != "direction_set":
            raise ValueError(f"slot {slot_id} is not a named direction set")
        direction_key = key.strip()
        if not direction_key:
            raise ValueError("direction key cannot be empty")
        vector = _direction_vector(start, end)
        directions = (
            list(node.get("params", {}).get("directions", []))
            if node.get("op") == "direction.manual_set@1.0"
            else []
        )
        replacement = {
            "key": direction_key,
            "vector": vector,
            "start": [float(value) for value in start],
            "end": [float(value) for value in end],
        }
        index = next(
            (i for i, item in enumerate(directions) if item.get("key") == direction_key),
            None,
        )
        if index is None:
            directions.append(replacement)
        else:
            directions[index] = replacement
        node.update(
            {
                "op": "direction.manual_set@1.0",
                "inputs": {},
                "params": {"directions": directions},
            }
        )
        return self._finish_draft(data)

    def bind_direction(
        self,
        package: SkillPackage,
        *,
        media_type: str,
        slot_id: str,
        start: list[float],
        end: list[float],
    ) -> SkillPackage:
        data = deepcopy(package.model_dump(mode="json"))
        slot, node = self._locate(data, media_type, slot_id)
        if slot["kind"] != "direction":
            raise ValueError(f"slot {slot_id} is not a single direction")
        vector = _direction_vector(start, end)
        node.update({
            "op": "direction.manual@1.0",
            "inputs": {},
            "params": {
                "vector": vector,
                "start": [float(value) for value in start],
                "end": [float(value) for value in end],
            },
        })
        return self._finish_draft(data)

    def clear_annotations(
        self,
        package: SkillPackage,
        *,
        media_type: str,
    ) -> SkillPackage:
        """Remove every saved manual region and direction in one variant.

        Clearing the canvas is intentionally broader than clearing the
        current unsaved draft: a user can have several named regions and
        dependent arrows saved in the same workflow.  Resetting their bound
        nodes to valid, empty manual values keeps the package reviewable while
        correctly returning required slots to ``needs_configuration``.
        Automatic regions and non-manual operators are left untouched.
        """

        data = deepcopy(package.model_dump(mode="json"))
        variant = data.get("variants", {}).get(media_type)
        if variant is None or variant.get("status") == "unsupported":
            raise ValueError(f"skill has no configurable {media_type} variant")

        for node in variant.get("nodes", []):
            op = node.get("op")
            if op == "region.manual@1.0":
                params = node.get("params", {})
                node["params"] = {
                    "shape": params.get("shape") or "rectangle",
                    "points": [],
                }
            elif op == "region.manual_set@1.0":
                node["params"] = {"regions": []}
            elif op == "direction.manual@1.0":
                node["params"] = {
                    "vector": [0.0, 0.0],
                    "start": None,
                    "end": None,
                }
            elif op == "direction.manual_set@1.0":
                node["params"] = {"directions": []}
        return self._finish_draft(data)

    def _finish_draft(self, data: dict[str, Any]) -> SkillPackage:
        _refresh_states(data)
        updated = SkillPackage.model_validate(data)
        from .validator import validate_skill_package

        errors = validate_skill_package(updated, self.registry)
        if errors:
            raise ValueError("\n".join(errors))
        return updated


__all__ = [
    "ConfigurationBinder",
    "configuration_status",
    "pending_required_slots",
]
