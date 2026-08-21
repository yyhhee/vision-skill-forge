from __future__ import annotations

import json
from pathlib import Path

from .media_assets import MediaAsset, MediaAssetStore


class PresetMediaCatalog:
    """Persistent preset candidates with explicit, type-safe default changes."""

    def __init__(self, path: str | Path, asset_store: MediaAssetStore):
        self.path = Path(path)
        self.asset_store = asset_store

    def _read(self) -> dict:
        if not self.path.is_file():
            return {"schema_version": "1.0", "presets": {}}
        data = json.loads(self.path.read_text("utf-8"))
        if data.get("schema_version") != "1.0":
            raise ValueError("unsupported preset media catalog schema")
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def _entry(asset: MediaAsset) -> dict:
        return {
            "asset_id": asset.asset_id,
            "original_name": asset.original_name,
            "stored_path": asset.stored_path,
        }

    def add_candidate(
        self, preset_name: str, media_path: str | Path, *, set_default: bool = False
    ) -> MediaAsset:
        asset = self.asset_store.ingest(media_path)
        data = self._read()
        media = (
            data.setdefault("presets", {})
            .setdefault(preset_name, {})
            .setdefault(asset.media_type, {"candidates": [], "default_asset_id": None})
        )
        if not any(
            item["asset_id"] == asset.asset_id for item in media["candidates"]
        ):
            media["candidates"].append(self._entry(asset))
        if set_default or media.get("default_asset_id") is None:
            media["default_asset_id"] = asset.asset_id
        self._write(data)
        return asset

    def set_default(
        self, preset_name: str, media_type: str, asset_id: str
    ) -> MediaAsset:
        data = self._read()
        media = data.get("presets", {}).get(preset_name, {}).get(media_type)
        candidate = next(
            (
                item
                for item in (media or {}).get("candidates", [])
                if item["asset_id"] == asset_id
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                f"asset {asset_id} is not a {media_type} candidate for {preset_name}"
            )
        media["default_asset_id"] = asset_id
        self._write(data)
        return self._asset_from_entry(candidate, media_type)

    @staticmethod
    def _asset_from_entry(entry: dict, media_type: str) -> MediaAsset:
        metadata_path = Path(entry["stored_path"]).parent / "metadata.json"
        asset = MediaAsset(**json.loads(metadata_path.read_text("utf-8")))
        if asset.media_type != media_type:
            raise ValueError("catalog media type does not match stored asset metadata")
        return asset

    def get_default(self, preset_name: str, media_type: str) -> MediaAsset | None:
        data = self._read()
        media = data.get("presets", {}).get(preset_name, {}).get(media_type)
        if not media or not media.get("default_asset_id"):
            return None
        entry = next(
            (
                item
                for item in media.get("candidates", [])
                if item["asset_id"] == media["default_asset_id"]
            ),
            None,
        )
        return None if entry is None else self._asset_from_entry(entry, media_type)

    def list_candidates(self, preset_name: str, media_type: str) -> list[dict]:
        data = self._read()
        media = data.get("presets", {}).get(preset_name, {}).get(media_type, {})
        default = media.get("default_asset_id")
        return [
            {**item, "is_default": item["asset_id"] == default}
            for item in media.get("candidates", [])
        ]


def _builtin_media_path(
    project_root: Path, preset_id: str, media_type: str
) -> Path:
    if media_type == "video":
        # The acceptance short clip is a 960x720 pillarboxed conversion.  The
        # original P05 demo preserves the road frame without black sidebars,
        # which keeps manually drawn lane overlays readable.
        if preset_id == "P05":
            demo = project_root / "data" / "demo_media" / "P05.mp4"
            if demo.is_file():
                return demo
        preferred = project_root / "data" / "acceptance_media" / "v2" / f"{preset_id}_positive.mp4"
        if preferred.is_file():
            return preferred
        if preset_id == "P12":
            preferred = project_root / "data" / "acceptance_media" / "v2" / "P12_positive_transition.mp4"
            if preferred.is_file():
                return preferred
        fallback = project_root / "data" / "demo_media" / f"{preset_id}.mp4"
        if fallback.is_file():
            return fallback
    else:
        image_overrides = {
            "P09": project_root / "data" / "acceptance_media" / "ppe_one_without_helmet.png",
        }
        preferred = image_overrides.get(preset_id)
        if preferred is not None and preferred.is_file():
            return preferred
        matches = sorted((project_root / "imgs").glob(f"{preset_id}*"))
        for candidate in matches:
            if candidate.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
                return candidate
        fallback = project_root / "data" / "demo_media" / f"{preset_id}.jpg"
        if fallback.is_file():
            return fallback
    raise FileNotFoundError(f"no builtin {media_type} media for {preset_id}")


def seed_builtin_preset_media(
    catalog: PresetMediaCatalog, project_root: str | Path
) -> list[MediaAsset]:
    """Idempotently seed one default per declared preset media variant."""

    from .schema import SkillPackage

    root = Path(project_root).resolve()
    seeded: list[MediaAsset] = []
    for preset_path in sorted((root / "presets_v2").glob("P*.json")):
        package = SkillPackage.model_validate_json(preset_path.read_text("utf-8"))
        preset_id = preset_path.stem[:3]
        for media_type in package.input.accept:
            path = _builtin_media_path(root, preset_id, media_type)
            asset = catalog.add_candidate(
                preset_path.stem, path, set_default=False
            )
            seeded.append(asset)
    return seeded


__all__ = ["PresetMediaCatalog", "seed_builtin_preset_media"]
