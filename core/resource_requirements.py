from __future__ import annotations

from copy import deepcopy
from typing import Any

from .editor_schema import (
    ResourceCollection,
    ResourceInstance,
    ResourceRequirement,
    SceneProfile,
    SkillTemplate,
)


_ROLE_LABELS = {
    "lane": "车道",
    "region": "区域",
    "direction": "方向",
    "lane_reference_direction": "车道方向",
}


def _collection(profile: SceneProfile, requirement_id: str) -> ResourceCollection:
    collection = next(
        (item for item in profile.collections if item.requirement_id == requirement_id),
        None,
    )
    if collection is None:
        collection = ResourceCollection(requirement_id=requirement_id)
        profile.collections.append(collection)
    return collection


def add_resource(
    profile: SceneProfile,
    requirement: ResourceRequirement,
    *,
    geometry: dict[str, Any],
    display_name: str | None = None,
    paired_resource_id: str | None = None,
) -> tuple[SceneProfile, ResourceInstance]:
    updated = deepcopy(profile)
    collection = _collection(updated, requirement.requirement_id)
    resource_type = (
        "region" if requirement.resource_type.startswith("region") else "direction"
    )
    base = _ROLE_LABELS.get(requirement.semantic_role, requirement.display_name)
    instance = ResourceInstance(
        resource_type=resource_type,
        display_name=(display_name or f"{base}{len(collection.items) + 1}").strip(),
        semantic_role=requirement.semantic_role,
        geometry=geometry,
        paired_resource_id=paired_resource_id,
    )
    collection.items.append(instance)
    collection.completed = False
    return updated, instance


def rename_resource(
    profile: SceneProfile, resource_id: str, display_name: str
) -> SceneProfile:
    name = display_name.strip()
    if not name:
        raise ValueError("display_name cannot be empty")
    updated = deepcopy(profile)
    for collection in updated.collections:
        for index, item in enumerate(collection.items):
            if item.resource_id == resource_id:
                collection.items[index] = item.model_copy(update={"display_name": name})
                return updated
    raise ValueError(f"unknown resource: {resource_id}")


def remove_resource(profile: SceneProfile, resource_id: str) -> SceneProfile:
    updated = deepcopy(profile)
    found = False
    for collection in updated.collections:
        remaining = [item for item in collection.items if item.resource_id != resource_id]
        if len(remaining) != len(collection.items):
            found = True
            collection.items = remaining
            collection.completed = False
        for index, item in enumerate(collection.items):
            if item.paired_resource_id == resource_id:
                collection.items[index] = item.model_copy(update={"paired_resource_id": None})
                collection.completed = False
    if not found:
        raise ValueError(f"unknown resource: {resource_id}")
    return updated


def complete_collection(profile: SceneProfile, requirement_id: str) -> SceneProfile:
    updated = deepcopy(profile)
    collection = _collection(updated, requirement_id)
    collection.completed = True
    return updated


def requirement_status(
    template: SkillTemplate, profile: SceneProfile
) -> list[dict[str, Any]]:
    collections = {item.requirement_id: item for item in profile.collections}
    statuses = []
    for requirement in template.resource_requirements:
        collection = collections.get(requirement.requirement_id)
        items = collection.items if collection is not None else []
        expected = None
        cardinality = requirement.cardinality
        if cardinality.mode == "exact":
            expected = cardinality.exact
            count_ok = len(items) == expected
        elif cardinality.mode == "dynamic":
            count_ok = len(items) >= cardinality.minimum and (
                cardinality.maximum is None or len(items) <= cardinality.maximum
            )
        else:
            source = collections.get(cardinality.source_requirement_id or "")
            expected_ids = {
                item.resource_id for item in (source.items if source is not None else [])
            }
            paired_ids = {item.paired_resource_id for item in items if item.paired_resource_id}
            expected = len(expected_ids)
            count_ok = bool(expected_ids) and paired_ids == expected_ids
        completed = bool(collection and collection.completed)
        configured = count_ok and completed
        statuses.append(
            {
                "requirement_id": requirement.requirement_id,
                "display_name": requirement.display_name,
                "resource_type": requirement.resource_type,
                "actual_count": len(items),
                "expected_count": expected,
                "completed": completed,
                "configured": configured,
                "required_before": requirement.required_before,
            }
        )
    return statuses


__all__ = [
    "add_resource",
    "complete_collection",
    "remove_resource",
    "rename_resource",
    "requirement_status",
]
