from __future__ import annotations

import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel

from .editor_schema import SkillEditorDocument
from .schema import SkillPackage, VisualSkillSpec


def write_json(path: Path, value) -> None:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value):
        value = asdict(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class SkillStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    @staticmethod
    def _validate_name(name: str) -> str:
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
            raise ValueError("技能标识必须以英文字母开头，且只能包含英文字母、数字、下划线或连字符")
        return name

    def save(
        self,
        spec: VisualSkillSpec,
        *,
        name: str | None = None,
        display_name: str | None = None,
    ) -> Path:
        data = spec.model_dump(mode="json")
        data["name"] = self._validate_name((name or spec.name).strip())
        data["display_name"] = (display_name or spec.display_name).strip()
        saved_spec = VisualSkillSpec.model_validate(data)
        directory = self.root / saved_spec.name
        directory.mkdir(parents=True, exist_ok=True)
        versions = [int(path.stem) for path in directory.glob("*.json") if path.stem.isdigit()]
        path = directory / f"{max(versions, default=0) + 1}.json"
        write_json(path, saved_spec)
        return path

    def load(self, name: str, version: int) -> VisualSkillSpec:
        name = self._validate_name(name)
        return VisualSkillSpec.model_validate_json(
            (self.root / name / f"{version}.json").read_text(encoding="utf-8")
        )

    def delete(self, name: str, version: int) -> Path:
        name = self._validate_name(name)
        if version < 1:
            raise ValueError("技能版本必须是正整数")
        directory = self.root / name
        path = directory / f"{version}.json"
        if not path.is_file():
            raise FileNotFoundError(f"自定义技能版本不存在：{name}/v{version}")
        path.unlink()
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        return path

    def list_versions(self) -> list[str]:
        if not self.root.exists():
            return []
        versions = []
        for path in self.root.glob("*/*.json"):
            if path.stem.isdigit():
                versions.append((path.parent.name, int(path.stem)))
        return [f"{name}/v{version}" for name, version in sorted(versions)]


class PackageStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def save(
        self,
        package: SkillPackage,
        *,
        skill_id: str | None = None,
        display_name: str | None = None,
    ) -> Path:
        identity = SkillStore._validate_name((skill_id or package.skill_id).strip())
        directory = self.root / identity
        directory.mkdir(parents=True, exist_ok=True)
        versions = [int(path.stem) for path in directory.glob("*.json") if path.stem.isdigit()]
        version = max(versions, default=0) + 1
        data = package.model_dump(mode="json")
        data["skill_id"] = identity
        data["display_name"] = (display_name or package.display_name).strip()
        data["version"] = version
        saved = SkillPackage.model_validate(data)
        path = directory / f"{version}.json"
        write_json(path, saved)
        return path

    def load(self, skill_id: str, version: int) -> SkillPackage:
        identity = SkillStore._validate_name(skill_id)
        return SkillPackage.model_validate_json(
            (self.root / identity / f"{version}.json").read_text(encoding="utf-8")
        )

    def delete(self, skill_id: str, version: int) -> Path:
        identity = SkillStore._validate_name(skill_id)
        if version < 1:
            raise ValueError("技能版本必须是正整数")
        directory = self.root / identity
        path = directory / f"{version}.json"
        if not path.is_file():
            raise FileNotFoundError(f"自定义技能版本不存在：{identity}/v{version}")
        path.unlink()
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
        return path

    def list_versions(self) -> list[str]:
        if not self.root.exists():
            return []
        versions = [
            (path.parent.name, int(path.stem))
            for path in self.root.glob("*/*.json")
            if path.stem.isdigit()
        ]
        return [f"{name}/v{version}" for name, version in sorted(versions)]


class SkillDocumentStore:
    """Version SkillEditorDocument while transparently importing legacy packages."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def save(
        self,
        document: SkillEditorDocument,
        *,
        skill_id: str | None = None,
        display_name: str | None = None,
    ) -> Path:
        identity = SkillStore._validate_name(
            (skill_id or document.skill_template.skill_id).strip()
        )
        directory = self.root / identity
        directory.mkdir(parents=True, exist_ok=True)
        versions = [int(path.stem) for path in directory.glob("*.json") if path.stem.isdigit()]
        version = max(versions, default=0) + 1
        template = document.skill_template.model_copy(
            update={
                "skill_id": identity,
                "display_name": (display_name or document.skill_template.display_name).strip(),
            }
        )
        saved = document.model_copy(update={"version": version, "skill_template": template})
        path = directory / f"{version}.json"
        write_json(path, saved)
        return path

    def load(self, skill_id: str, version: int) -> SkillEditorDocument:
        identity = SkillStore._validate_name(skill_id)
        path = self.root / identity / f"{version}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") == "3.0":
            return SkillEditorDocument.model_validate(data)
        if data.get("schema_version") == "2.0":
            from .legacy_importer import import_skill_package

            return import_skill_package(SkillPackage.model_validate(data))
        raise ValueError(f"unsupported skill document schema: {data.get('schema_version')}")

    def list_versions(self) -> list[str]:
        if not self.root.exists():
            return []
        versions = [
            (path.parent.name, int(path.stem))
            for path in self.root.glob("*/*.json")
            if path.stem.isdigit()
        ]
        return [f"{name}/v{version}" for name, version in sorted(versions)]


class RunStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def create(self) -> tuple[str, Path]:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
        run_dir = self.root / run_id
        (run_dir / "evidence").mkdir(parents=True, exist_ok=False)
        return run_id, run_dir


__all__ = [
    "PackageStore",
    "RunStore",
    "SkillDocumentStore",
    "SkillStore",
    "write_json",
]
