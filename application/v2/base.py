"""ApplicationContext: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from application.v2.support import ROOT, ApplicationError, _variant_key
from core.business_capabilities import build_business_capability_registry
from core.business_rule_editor import BusinessRuleEditor
from core.configuration import ConfigurationBinder, configuration_status
from core.editor_migrations import migrate_editor_document
from core.editor_schema import (
    SkillEditorDocument,
)
from core.editor_service import EditorService
from core.media_assets import MediaAssetStore
from core.persistence import PackageStore, RunStore, SkillDocumentStore
from core.preset_media import PresetMediaCatalog
from core.registry import OperatorRegistry
from core.schema import SkillPackage


class ApplicationContext:
    def __init__(
        self,
        *,
        registry: OperatorRegistry,
        package_root: Path,
        run_root: Path,
        planner,
        rex,
        asset_root: Path | None = None,
        preset_catalog_path: Path | None = None,
    ):
        self.registry = registry
        self.package_store = PackageStore(package_root)
        self.document_store = SkillDocumentStore(
            package_root.parent / "skill_documents"
        )
        self.run_store = RunStore(run_root)
        self.planner = planner
        self.rex = rex
        self.preset_root = ROOT / "presets_v2"
        self.asset_store = MediaAssetStore(
            asset_root or package_root.parent / "media_assets"
        )
        self.preset_media_catalog = PresetMediaCatalog(
            preset_catalog_path or package_root.parent / "preset_media_defaults.json",
            self.asset_store,
        )
        self.configuration_binder = ConfigurationBinder(registry)
        self.editor_service = EditorService(registry)
        self.business_capabilities = build_business_capability_registry(registry)
        self.business_rule_editor = BusinessRuleEditor(
            self.business_capabilities, registry
        )
        self._generated_editor_documents: dict[str, SkillEditorDocument] = {}

    @staticmethod
    def _dump(value: Any) -> str:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return json.dumps(value, ensure_ascii=False, indent=2)

    @staticmethod
    def _parse_editor_json(value: str) -> SkillEditorDocument:
        if not value or not value.strip():
            raise ValueError("请先生成或加载技能，再编辑事件规则。")
        return migrate_editor_document(json.loads(value))

    def preferred_executable_variant(
        self, effective_json: str, preferred: str = "image"
    ) -> str:
        """Choose a real executable variant rather than trusting a UI default."""

        if not effective_json or not effective_json.strip():
            return _variant_key(preferred)
        package = SkillPackage.model_validate_json(effective_json)
        preferred_key = _variant_key(preferred)
        candidates = [preferred_key, *package.input.accept]
        for key in dict.fromkeys(candidates):
            variant = package.variants.get(key)
            if variant is not None and variant.status != "unsupported":
                return key
        raise ApplicationError("当前技能没有可执行的图片或视频流程")

    @staticmethod
    def _instruction_identity(value: str) -> str:
        """Normalize harmless punctuation/spacing for safe draft reuse."""

        return re.sub(r"[\s，,。.!！?？；;：:]+", "", value or "").casefold()

    def _reuse_matching_manual_annotations(
        self, package: SkillPackage, previous_effective_json: str
    ) -> tuple[SkillPackage, int]:
        """Carry saved scene geometry across regeneration of the same task.

        A natural-language regeneration rebuilds the Effective package from
        scratch. Manual regions and directions are scene configuration, not
        rule-generation output, so dropping them makes an unchanged task fail
        at run time. Reuse is deliberately strict: both skill identity and
        normalized instruction must match, and every slot must still match by
        id, kind and label. Unrelated tasks can therefore never inherit stale
        geometry merely because they use generic names such as ``区域1``.
        """

        if not (previous_effective_json or "").strip():
            return package, 0
        try:
            previous = SkillPackage.model_validate_json(previous_effective_json)
        except (ValueError, TypeError):
            return package, 0
        if previous.skill_id != package.skill_id:
            return package, 0
        if self._instruction_identity(
            previous.original_instruction
        ) != self._instruction_identity(package.original_instruction):
            return package, 0

        configured = {
            (item["media_type"], item["slot_id"]): item["configured"]
            for item in configuration_status(previous)
        }
        updated = package
        reused = 0
        # Regions must be restored before directions that may depend on their
        # ids. Each bind passes through the normal schema and DAG validator.
        kind_order = {"region": 0, "region_set": 1, "direction": 2, "direction_set": 3}
        for media_type, variant in package.variants.items():
            old_variant = previous.variants.get(media_type)
            if old_variant is None or old_variant.status == "unsupported":
                continue
            old_slots = {slot.slot_id: slot for slot in old_variant.configuration_slots}
            old_nodes = {node.id: node for node in old_variant.nodes}
            for slot in sorted(
                variant.configuration_slots,
                key=lambda item: kind_order.get(item.kind, 99),
            ):
                old_slot = old_slots.get(slot.slot_id)
                if (
                    old_slot is None
                    or old_slot.kind != slot.kind
                    or old_slot.label != slot.label
                    or not configured.get((media_type, old_slot.slot_id), False)
                ):
                    continue
                node = old_nodes.get(old_slot.binding.node_id)
                if node is None:
                    continue
                params = node.params
                try:
                    if slot.kind == "region":
                        updated = self.configuration_binder.bind_region(
                            updated,
                            media_type=media_type,
                            slot_id=slot.slot_id,
                            shape=params["shape"],
                            points=params["points"],
                        )
                    elif slot.kind == "region_set":
                        for region in params.get("regions", []):
                            updated = self.configuration_binder.bind_named_region(
                                updated,
                                media_type=media_type,
                                slot_id=slot.slot_id,
                                region_id=region["id"],
                                label=region.get("label", region["id"]),
                                shape=region["shape"],
                                points=region["points"],
                            )
                    elif slot.kind == "direction":
                        updated = self.configuration_binder.bind_direction(
                            updated,
                            media_type=media_type,
                            slot_id=slot.slot_id,
                            start=params["start"],
                            end=params["end"],
                        )
                    else:
                        for direction in params.get("directions", []):
                            updated = self.configuration_binder.bind_named_direction(
                                updated,
                                media_type=media_type,
                                slot_id=slot.slot_id,
                                key=direction["key"],
                                start=direction["start"],
                                end=direction["end"],
                            )
                except (KeyError, TypeError, ValueError):
                    # A changed slot schema is not compatible; leave that slot
                    # pending so the user must draw it explicitly.
                    continue
                reused += 1
        return updated, reused

    @staticmethod
    def editor_variant_for_media(media_type: str) -> str:
        return f"{_variant_key(media_type)} variant"

    @classmethod
    def cleared_task_media_state(cls):
        return (
            "",
            {},
            None,
            {},
            "已清除当前任务媒体；已运行结果和产物目录不受影响。",
            "image",
            "image",
            cls.runtime_media_summary("", "image"),
            "image variant",
        )
