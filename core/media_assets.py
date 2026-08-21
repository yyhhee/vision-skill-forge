from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .media_policy import read_media_metadata


@dataclass(frozen=True)
class MediaAsset:
    asset_id: str
    media_type: str
    original_name: str
    original_path: str
    stored_path: str
    width: int
    height: int
    fps: float | None
    frame_count: int | None
    duration_seconds: float | None
    byte_size: int
    ingested_at: str


class MediaAssetStore:
    """Content-addressed storage for immutable, user-uploaded media bytes."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def ingest(self, source: str | Path) -> MediaAsset:
        source_path = Path(source).resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"media file does not exist: {source_path}")
        asset_id = self._sha256(source_path)
        directory = self.root / asset_id
        metadata_path = directory / "metadata.json"
        if metadata_path.is_file():
            return MediaAsset(**json.loads(metadata_path.read_text("utf-8")))

        metadata = read_media_metadata(source_path)
        directory.mkdir(parents=True, exist_ok=True)
        stored_path = directory / f"original{source_path.suffix.lower()}"
        shutil.copyfile(source_path, stored_path)
        asset = MediaAsset(
            asset_id=asset_id,
            media_type=metadata.media_type,
            original_name=source_path.name,
            original_path=str(source_path),
            stored_path=str(stored_path.resolve()),
            width=metadata.width,
            height=metadata.height,
            fps=metadata.fps,
            frame_count=metadata.frame_count,
            duration_seconds=metadata.duration_seconds,
            byte_size=source_path.stat().st_size,
            ingested_at=datetime.now(timezone.utc).isoformat(),
        )
        metadata_path.write_text(
            json.dumps(asdict(asset), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return asset


__all__ = ["MediaAsset", "MediaAssetStore"]

