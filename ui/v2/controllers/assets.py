"""AssetController: extracted V2 responsibilities, preserving public method signatures."""

from __future__ import annotations

from core.effective_package_view import build_effective_package_view
from core.operator_asset_catalog import build_operator_asset_catalog
from core.schema import SkillPackage


class AssetController:
    def business_capability_detail(self, capability_id: str):
        return self.business_capabilities.require(capability_id).model_dump(mode="json")

    def operator_asset_detail(self, operator: str, editor_json: str = ""):
        document = self._parse_editor_json(editor_json) if editor_json else None
        catalog = build_operator_asset_catalog(self.registry, document)
        return next(item for item in catalog if item["operator"] == operator)

    def effective_package_asset_view(self, effective_json: str, editor_json: str = ""):
        if not effective_json:
            return {"status": "尚未生成或加载技能"}
        package = SkillPackage.model_validate_json(effective_json)
        document = self._parse_editor_json(editor_json) if editor_json else None
        return build_effective_package_view(package, document)
