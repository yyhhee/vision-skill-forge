from __future__ import annotations

from pathlib import Path

from core.preset_definitions import build_preset_definitions
from core.preset_factory import write_packages


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    paths = write_packages(
        build_preset_definitions(),
        ROOT / "presets_v2",
    )
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
