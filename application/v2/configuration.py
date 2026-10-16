"""One draft/activation boundary for original V2 configuration editing.

Publication metadata lives with the portable editor document.  It is not a
second mutable skill, and it is excluded from the configuration fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.editor_schema import SkillEditorDocument
from core.schema import SkillPackage

from .support import ApplicationError

if TYPE_CHECKING:
    from core.editor_service import EditorService

_PUBLICATION = "configuration_publication"


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def configuration_hash(document: SkillEditorDocument) -> str:
    """Fingerprint editable content, excluding reports and derived run artifacts."""
    return _digest(
        {
            "template": document.skill_template.model_dump(mode="json"),
            "profiles": [
                item.model_dump(mode="json") for item in document.scene_profiles
            ],
            "active_profile": document.active_scene_profile_id,
            "overrides": [
                item.model_dump(mode="json") for item in document.user_overrides
            ],
        }
    )


def package_hash(package: SkillPackage) -> str:
    return _digest(package.model_dump(mode="json"))


@dataclass(frozen=True)
class ConfigurationStatus:
    dirty: bool
    running_revision: int | None
    package_matches: bool


class ConfigurationService:
    """Stage business edits and activate only a fully validated copy."""

    def __init__(self, editor_service: EditorService) -> None:
        self.editor_service = editor_service

    def initialize(self, document: SkillEditorDocument) -> SkillEditorDocument:
        """Attach a baseline after load-time business projection has completed."""
        result = document.model_copy(deep=True)
        if _PUBLICATION not in result.validation_report:
            result.validation_report[_PUBLICATION] = self.publication(result)
        return result

    @staticmethod
    def publication(document: SkillEditorDocument) -> dict:
        recorded = document.validation_report.get(_PUBLICATION)
        if isinstance(recorded, dict):
            if recorded:
                revision = recorded.get("revision")
                if (
                    not isinstance(revision, int)
                    or isinstance(revision, bool)
                    or revision < 1
                    or any(
                        not isinstance(recorded.get(key), str)
                        or not re.fullmatch(r"[0-9a-f]{64}", recorded[key])
                        for key in ("configuration_hash", "package_hash")
                    )
                ):
                    raise ApplicationError("配置版本记录无效，请重新加载技能。")
            return dict(recorded)
        # Historical documents have no publication record. Bootstrap only an
        # existing clean executable document, never an invalidated draft.
        if (
            document.effective_skill_package is not None
            and not document.validation_report.get("dirty")
        ):
            return {
                "revision": 1,
                "configuration_hash": configuration_hash(document),
                "package_hash": package_hash(document.effective_skill_package),
            }
        return {}

    def stage(
        self, before: SkillEditorDocument, updated: SkillEditorDocument
    ) -> SkillEditorDocument:
        """Keep the last published identity while invalidating edited content."""
        result = updated.model_copy(deep=True)
        if result.skill_template.skill_id != before.skill_template.skill_id:
            raise ApplicationError("配置修改不能切换技能，请从 01 重新加载。")
        publication = self.publication(before)
        changed = configuration_hash(before) != configuration_hash(result)
        dirty = bool(changed or before.validation_report.get("dirty"))
        if publication:
            dirty = dirty or configuration_hash(result) != publication.get(
                "configuration_hash"
            )
        result.validation_report = {
            **result.validation_report,
            _PUBLICATION: publication,
            "dirty": dirty,
            "can_run": False
            if dirty
            else result.validation_report.get("can_run", False),
        }
        if dirty:
            result.effective_skill_package = None
            result.readiness.runtime_ready = False
            result.readiness.publish_ready = False
        elif not changed:
            result.effective_skill_package = before.effective_skill_package
            result.validation_report["can_run"] = before.validation_report.get(
                "can_run", False
            )
        return result

    def publish(self, document: SkillEditorDocument) -> SkillEditorDocument:
        """Never mutate the caller or replace its run package on failed validation."""
        previous = self.publication(document)
        compiled = self.editor_service.apply(document.model_copy(deep=True))
        if compiled.effective_skill_package is None:
            raise ApplicationError("校验未生成运行版本；上一运行版本保持不变。")
        report = compiled.validation_report
        if report.get("errors") or report.get("pending"):
            details = [*report.get("errors", []), *report.get("pending", [])]
            raise ApplicationError("配置尚未完成：" + "；".join(map(str, details)))
        # Required geometry can be bound in 02 after compilation, as in the
        # existing workflow. Such a revision is explicitly marked not runnable.
        compiled.validation_report[_PUBLICATION] = {
            "revision": int(previous.get("revision", 0)) + 1,
            "configuration_hash": configuration_hash(compiled),
            "package_hash": package_hash(compiled.effective_skill_package),
        }
        compiled.validation_report["dirty"] = False
        return compiled

    def status(
        self, document: SkillEditorDocument, effective: SkillPackage
    ) -> ConfigurationStatus:
        publication = self.publication(document)
        dirty = bool(document.validation_report.get("dirty"))
        if publication:
            dirty = dirty or configuration_hash(document) != publication.get(
                "configuration_hash"
            )
        else:
            dirty = dirty or document.effective_skill_package is None
        matches = (
            publication.get("package_hash") == package_hash(effective)
            if publication
            else document.effective_skill_package == effective
        )
        return ConfigurationStatus(dirty, publication.get("revision"), matches)

    def accept_runtime_update(
        self, before: SkillEditorDocument, updated: SkillEditorDocument
    ) -> SkillEditorDocument:
        """Record explicit 02/execution-card package updates without losing drafts.

        Those existing controls already validate a complete package. They may
        advance a clean running version, but must never erase a staged edit.
        """
        if before.effective_skill_package is None:
            raise ApplicationError("有未应用修改，请先应用草稿，再修改运行参数。")
        old = self.status(before, before.effective_skill_package)
        if old.dirty:
            raise ApplicationError("有未应用修改，请先应用草稿，再修改运行参数。")
        result = updated.model_copy(deep=True)
        if result.effective_skill_package is None:
            raise ApplicationError("运行参数更新未提供运行包。")
        previous = self.publication(before)
        result.validation_report[_PUBLICATION] = {
            "revision": int(previous.get("revision", 0)) + 1,
            "configuration_hash": configuration_hash(result),
            "package_hash": package_hash(result.effective_skill_package),
        }
        result.validation_report["dirty"] = False
        return result

    def require_current(
        self, document: SkillEditorDocument, effective: SkillPackage
    ) -> None:
        if document.skill_template.skill_id != effective.skill_id:
            raise ApplicationError("编辑草稿与运行版本不是同一个技能，请重新加载。")
        state = self.status(document, effective)
        if state.dirty or document.effective_skill_package is None:
            raise ApplicationError(
                "有未应用修改，请先在 03 点击“应用修改，更新运行版本”。当前不会运行旧配置。"
            )
        if not state.package_matches:
            raise ApplicationError(
                "当前运行版本与草稿记录不一致，请重新读取配置后应用。"
            )


__all__ = [
    "ConfigurationService",
    "ConfigurationStatus",
    "configuration_hash",
    "package_hash",
]
