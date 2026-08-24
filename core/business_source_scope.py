from __future__ import annotations

from collections.abc import Iterable

from .editor_schema import ConditionExpression, SkillTemplate


def _walk(root: ConditionExpression | None):
    if root is None:
        return
    yield root
    for child in root.children:
        yield from _walk(child)


def source_media_types(
    template: SkillTemplate,
    source_ref: str | None,
    *,
    _resolving: set[str] | None = None,
) -> set[str]:
    """Return the variants that own a stable business source.

    An empty set means the reference is package-global/legacy and may be used
    by every requested variant. It never means that a known cross-media source
    should be silently accepted.
    """

    if not source_ref or ":" not in source_ref:
        return set()
    resolving = _resolving if _resolving is not None else set()
    if source_ref in resolving:
        return set()
    resolving.add(source_ref)
    try:
        prefix, key = source_ref.split(":", 1)
        if prefix == "branch":
            branch = next(
                (
                    item
                    for item in template.business_branches
                    if item.branch_id == key
                ),
                None,
            )
            return {branch.media_type} if branch is not None else set()
        if prefix in {"condition", "measurement"}:
            for branch in template.business_branches:
                if any(item.expression_id == key for item in _walk(branch.condition_root)):
                    return {branch.media_type}
            return set()
        if prefix == "event":
            pattern = next(
                (
                    item
                    for item in template.event_patterns
                    if item.pattern_id == key
                ),
                None,
            )
            return {pattern.media_type} if pattern is not None else set()
        if prefix == "result":
            spec = next(
                (item for item in template.result_specs if item.result_id == key),
                None,
            )
            if spec is None:
                return set()
            if spec.media_types:
                return set(spec.media_types)
            return source_media_types(
                template, spec.source_ref, _resolving=resolving
            )
        if prefix == "final":
            return {
                branch.media_type
                for branch in template.business_branches
                if branch.enabled
            }
        return set()
    finally:
        resolving.discard(source_ref)


def partition_source_refs(
    template: SkillTemplate,
    source_refs: Iterable[str],
    media_types: Iterable[str],
) -> dict[str, list[str]]:
    requested = list(dict.fromkeys(media_types))
    result = {media_type: [] for media_type in requested}
    for source_ref in dict.fromkeys(source_refs):
        scoped = source_media_types(template, source_ref)
        targets = scoped or set(requested)
        for media_type in requested:
            if media_type in targets:
                result[media_type].append(source_ref)
    return {key: value for key, value in result.items() if value}


__all__ = ["partition_source_refs", "source_media_types"]
