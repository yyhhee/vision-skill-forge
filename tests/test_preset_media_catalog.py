from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from core.media_assets import MediaAssetStore
from core.preset_media import PresetMediaCatalog


def test_replacement_upload_does_not_change_default_until_explicit_set(tmp_path):
    store = MediaAssetStore(tmp_path / "assets")
    catalog = PresetMediaCatalog(tmp_path / "catalog.json", store)
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (20, 10), "red").save(first)
    Image.new("RGB", (20, 10), "blue").save(second)

    initial = catalog.add_candidate("P01_fire_smoke", first, set_default=True)
    replacement = store.ingest(second)
    assert catalog.get_default("P01_fire_smoke", "image").asset_id == initial.asset_id
    assert replacement.asset_id != initial.asset_id

    catalog.add_candidate("P01_fire_smoke", second, set_default=False)
    assert catalog.get_default("P01_fire_smoke", "image").asset_id == initial.asset_id
    catalog.set_default("P01_fire_smoke", "image", replacement.asset_id)
    assert catalog.get_default("P01_fire_smoke", "image").asset_id == replacement.asset_id


def test_catalog_rejects_cross_type_default_and_lists_candidates(tmp_path):
    store = MediaAssetStore(tmp_path / "assets")
    catalog = PresetMediaCatalog(tmp_path / "catalog.json", store)
    image = tmp_path / "sample.png"
    Image.new("RGB", (12, 8), "white").save(image)
    asset = catalog.add_candidate("P09_no_helmet", image, set_default=True)

    with pytest.raises(ValueError, match="is not a video candidate"):
        catalog.set_default("P09_no_helmet", "video", asset.asset_id)

    rows = catalog.list_candidates("P09_no_helmet", "image")
    assert rows == [
        {
            "asset_id": asset.asset_id,
            "original_name": "sample.png",
            "stored_path": asset.stored_path,
            "is_default": True,
        }
    ]


def test_builtin_defaults_cover_every_supported_p01_to_p13_variant(tmp_path):
    from core.preset_media import seed_builtin_preset_media
    from core.schema import SkillPackage

    project_root = Path(__file__).resolve().parents[1]
    catalog = PresetMediaCatalog(
        tmp_path / "catalog.json", MediaAssetStore(tmp_path / "assets")
    )

    seeded = seed_builtin_preset_media(catalog, project_root)

    preset_files = sorted((project_root / "presets_v2").glob("P*.json"))
    assert len(preset_files) == 13
    expected = 0
    for path in preset_files:
        package = SkillPackage.model_validate_json(path.read_text("utf-8"))
        for media_type in package.input.accept:
            expected += 1
            asset = catalog.get_default(path.stem, media_type)
            assert asset is not None, (path.stem, media_type)
            assert asset.media_type == media_type
            assert Path(asset.stored_path).is_file()
    assert len(seeded) == expected == 21


def test_builtin_seeding_repairs_a_default_from_a_missing_source_asset(tmp_path):
    from core.preset_media import seed_builtin_preset_media

    project_root = Path(__file__).resolve().parents[1]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(
        '{"schema_version":"1.0","presets":{"P01_fire_smoke":{"image":{'
        '"candidates":[{"asset_id":"old","original_name":"old.png",'
        '"stored_path":"C:/missing/media_assets/old/original.png"}],'
        '"default_asset_id":"old"}}}}',
        encoding="utf-8",
    )
    catalog = PresetMediaCatalog(catalog_path, MediaAssetStore(tmp_path / "assets"))

    seed_builtin_preset_media(catalog, project_root)

    default = catalog.get_default("P01_fire_smoke", "image")
    assert default is not None
    assert Path(default.stored_path).is_file()
    assert default.original_name == "P01_fire_smoke.jpg"
