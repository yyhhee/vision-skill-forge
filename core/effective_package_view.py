from __future__ import annotations

import hashlib
import json
from typing import Any

from .editor_schema import SkillEditorDocument
from .schema import SkillPackage


def _hash_package(package: SkillPackage) -> str:
    canonical = json.dumps(
        package.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_effective_package_view(
    package: SkillPackage,
    document: SkillEditorDocument | None = None,
) -> dict[str, Any]:
    actual_package_hash = _hash_package(package)
    document_package_hash = document.hashes.package_hash if document else None
    variants = []
    for media_type, variant in sorted(package.variants.items()):
        variants.append(
            {
                "media_type": media_type,
                "status": variant.status,
                "operator_count": len(variant.nodes),
                "outputs": sorted(variant.outputs),
                "configuration_slots": [
                    {
                        "slot_id": item.slot_id,
                        "label": item.label,
                        "kind": item.kind,
                        "required": item.required,
                    }
                    for item in variant.configuration_slots
                ],
            }
        )
    return {
        "schema_version": "1.0",
        "skill_id": package.skill_id,
        "version": package.version,
        "display_name": package.display_name,
        "compile_status": package.compile_status,
        "requested_media": package.input.requested_accept,
        "executable_media": package.input.accept,
        "variants": variants,
        "hashes": {
            "semantic_hash": document.hashes.semantic_hash if document else None,
            "compile_hash": document.hashes.compile_hash if document else None,
            "package_hash": actual_package_hash,
            "presentation_hash": document.hashes.presentation_hash if document else None,
        },
        "document_package_hash": document_package_hash,
        "package_hash_matches_document": (
            document_package_hash == actual_package_hash
            if document_package_hash is not None
            else None
        ),
        "effective_skill_package": package.model_dump(mode="json"),
    }


__all__ = ["build_effective_package_view"]
