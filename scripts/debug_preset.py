from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from clients.rex_client import RexGateway
from core.context import ExecutionServices
from core.executor import ExecutionEngine
from core.registry import build_default_registry
from core.schema import VisualSkillSpec
from operators import build_default_implementations


def main(preset_id: str):
    preset_path = next((ROOT / "presets").glob(f"{preset_id}*.json"))
    media = next((ROOT / "data" / "demo_media").glob(f"{preset_id}.*"))
    spec = VisualSkillSpec.model_validate_json(preset_path.read_text("utf-8"))
    result = ExecutionEngine(
        build_default_registry(), build_default_implementations(),
        ExecutionServices(RexGateway(), ROOT / "data" / "debug" / preset_id),
    ).execute(spec, media)
    for name, value in result.values.items():
        items = getattr(value, "items", None)
        if items is None:
            continue
        sample = []
        for item in items[:8]:
            sample.append({key: getattr(item, key) for key in ("key", "timestamp", "value") if hasattr(item, key)})
        print(name, len(items), sample)


if __name__ == "__main__":
    main(sys.argv[1])
